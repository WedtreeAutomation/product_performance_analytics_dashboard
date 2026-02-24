import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import numpy as np
from azure.identity import ClientSecretCredential
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from io import BytesIO
from PIL import Image
import warnings
warnings.filterwarnings('ignore')

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Product Launch Performance Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        color: #1E88E5;
        text-align: center;
        margin-bottom: 1rem;
        padding: 1rem;
        background: linear-gradient(90deg, #f8f9fa 0%, #e9ecef 100%);
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        text-align: center;
        margin: 0.5rem 0;
        transition: transform 0.3s ease;
    }
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.15);
    }
    .metric-value {
        font-size: 2.2rem;
        font-weight: bold;
        color: #1E88E5;
    }
    .metric-label {
        font-size: 1rem;
        color: #666;
        margin-top: 0.5rem;
    }
    .metric-subtext {
        font-size: 0.9rem;
        color: #999;
        margin-top: 0.25rem;
        padding-top: 0.25rem;
        border-top: 1px solid #eee;
    }
    .stAlert {
        border-radius: 10px;
    }
    .product-image {
        border-radius: 10px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .product-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
        gap: 1rem;
        padding: 1rem 0;
    }
    .product-card {
        background: white;
        border-radius: 10px;
        padding: 1rem;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        transition: transform 0.2s ease;
    }
    .product-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.15);
    }
    </style>
""", unsafe_allow_html=True)

# Initialize credentials from environment variables
@st.cache_resource
def init_credentials():
    """Initialize and cache Azure credentials"""
    return {
        "client_id": os.getenv("AZURE_CLIENT_ID"),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET"),
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "endpoint": os.getenv("FABRIC_ENDPOINT"),
        "shopify_endpoint": os.getenv("SHOPIFY_ENDPOINT"),
        "shopify_token": os.getenv("SHOPIFY_ACCESS_TOKEN")
    }

# Initialize headers
@st.cache_resource
def get_headers(creds):
    """Get authenticated headers for Fabric API"""
    try:
        credential = ClientSecretCredential(
            creds["tenant_id"], 
            creds["client_id"], 
            creds["client_secret"]
        )
        scope = 'https://api.fabric.microsoft.com/.default'
        token = credential.get_token(scope).token
        
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
    except Exception as e:
        st.error(f"Authentication failed: {e}")
        return None

def fetch_product_image_by_category(category, product_title=None):
    """Fetch product image from Shopify using category and optional title"""
    try:
        creds = init_credentials()
        
        # Build query based on category and optional title
        if product_title:
            query_str = f"product_type:{category} AND title:{product_title}"
        else:
            query_str = f"product_type:{category}"
        
        # First try to get products by category
        graphql_query = """
        query getProductsByType($query: String!) {
          products(first: 5, query: $query) {
            edges {
              node {
                title
                productType
                images(first: 1) {
                  edges {
                    node {
                      url
                      altText
                    }
                  }
                }
                variants(first: 1) {
                  edges {
                    node {
                      sku
                      image {
                        url
                      }
                    }
                  }
                }
              }
            }
          }
        }
        """

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": creds["shopify_token"]
        }

        response = requests.post(
            creds["shopify_endpoint"],
            headers=headers,
            json={"query": graphql_query, "variables": {"query": query_str}},
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        if "errors" in data or not data.get("data", {}).get("products", {}).get("edges"):
            return None

        products = data["data"]["products"]["edges"]
        
        # Try to find an image from any product in this category
        for product in products:
            node = product["node"]
            
            # Check variant images first
            if node.get("variants", {}).get("edges"):
                for variant in node["variants"]["edges"]:
                    if variant["node"].get("image") and variant["node"]["image"].get("url"):
                        return variant["node"]["image"]["url"]
            
            # Check product images
            if node.get("images", {}).get("edges"):
                return node["images"]["edges"][0]["node"].get("url")
        
        return None

    except Exception as e:
        return None

def load_image_from_url(url):
    """Load image from URL and return PIL Image"""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        return img
    except:
        return None

# Data fetching functions with caching
@st.cache_data(ttl=300)
def get_products(product_created_date):
    """Fetch products launched on a specific date"""
    try:
        creds = init_credentials()
        headers = get_headers(creds)
        
        if not headers:
            return pd.DataFrame()
        
        query = """
        query GetProducts($ProductCreatedDate: DateTime) {
            executesp_products(ProductCreatedDate: $ProductCreatedDate) {
                product_id
                sku
                productType
                product_created
            }
        }
        """
        
        variables = {"ProductCreatedDate": product_created_date}
        
        response = requests.post(
            creds["endpoint"],
            headers=headers,
            json={"query": query, "variables": variables}
        )
        
        response.raise_for_status()
        items = response.json().get("data", {}).get("executesp_products", [])
        
        if not items:
            return pd.DataFrame(columns=["product_id", "sku", "productType", "product_created"])
        
        df = pd.DataFrame(items)
        return df
        
    except Exception as e:
        st.error(f"Error loading products: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def get_inventory_data(order_start, order_end):
    """Fetch inventory and sales data"""
    try:
        creds = init_credentials()
        headers = get_headers(creds)
        
        if not headers:
            return pd.DataFrame()
        
        query = """
        query GetInventory(
            $orderStart: DateTime
            $orderEnd: DateTime
        ) {
            executesp_inventory(
                OrderStartDate: $orderStart
                OrderEndDate: $orderEnd
            ) {
                product_id
                sku
                title
                product_category
                totalInventory
                order_id
                order_createdAt
                product_createdAt
                quantity
            }
        }
        """
        
        variables = {
            "orderStart": order_start,
            "orderEnd": order_end
        }
        
        response = requests.post(
            creds["endpoint"],
            headers=headers,
            json={"query": query, "variables": variables}
        )
        
        response.raise_for_status()
        items = response.json().get("data", {}).get("executesp_inventory", [])
        
        if not items:
            return pd.DataFrame()
        
        df = pd.DataFrame(items)
        
        # Data processing
        if 'totalInventory' in df.columns:
            df['totalInventory'] = df['totalInventory'].apply(lambda x: max(x, 0) if pd.notna(x) else 0)
        
        if 'product_createdAt' in df.columns:
            df['product_createdAt'] = pd.to_datetime(df['product_createdAt'], errors='coerce')
        
        if 'order_createdAt' in df.columns:
            df['order_createdAt'] = pd.to_datetime(df['order_createdAt'], errors='coerce')
        
        if 'quantity' in df.columns:
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
        
        return df
        
    except Exception as e:
        st.error(f"Error loading inventory: {e}")
        return pd.DataFrame()

def calculate_metrics(launch_df, sales_df, launch_date):
    """Calculate all required metrics"""
    metrics = {}
    
    # Card 1: Products Launched
    metrics['products_launched'] = len(launch_df) if not launch_df.empty else 0

    categories_launched = launch_df['productType'].unique().tolist()
    
    # Card 2: Categories
    metrics['categories'] = len(categories_launched) if not launch_df.empty else 0
    
    # Card 3: SKU Sold within Range
    if not sales_df.empty and not launch_df.empty:
        launch_dt = pd.to_datetime(launch_date).date()
        
        # New products (launched on selected date)
        new_products = sales_df[
            sales_df['product_createdAt'].dt.date == launch_dt
        ]
        new_skus_sold = new_products['sku'].nunique() if not new_products.empty else 0
        
        # Old products (existing before launch date)
        old_products = sales_df[
            (sales_df['product_createdAt'].dt.date < launch_dt) & (sales_df['product_category'].isin(categories_launched))
        ]
        old_skus_sold = old_products['sku'].nunique() if not old_products.empty else 0
        
        metrics['new_skus_sold'] = new_skus_sold
        metrics['old_skus_sold'] = old_skus_sold
    else:
        metrics['new_skus_sold'] = 0
        metrics['old_skus_sold'] = 0
    
    # Card 4: Quantity Sold within Range
    if not sales_df.empty and not launch_df.empty:
        launch_dt = pd.to_datetime(launch_date).date()
        
        # New products quantity
        new_products = sales_df[
            sales_df['product_createdAt'].dt.date == launch_dt
        ]
        new_products_qty = new_products['quantity'].sum() if not new_products.empty else 0
        
        # Old products quantity
        old_products = sales_df[
            (sales_df['product_createdAt'].dt.date < launch_dt) & (sales_df['product_category'].isin(categories_launched))
        ]
        old_products_qty = old_products['quantity'].sum() if not old_products.empty else 0
        
        metrics['new_qty_sold'] = int(new_products_qty)
        metrics['old_qty_sold'] = int(old_products_qty)
    else:
        metrics['new_qty_sold'] = 0
        metrics['old_qty_sold'] = 0
    
    return metrics

def display_product_card(product_data, inventory_data, category):
    """Display a single product card with image and details"""
    sku = product_data['sku']
    title = product_data['title']
    
    # Get sales data for this product
    product_sales = inventory_data[
        (inventory_data['sku'] == sku)
    ]
    
    if not product_sales.empty:
        total_sold = product_sales['quantity'].sum()
        current_stock = product_sales['totalInventory'].iloc[0] if 'totalInventory' in product_sales.columns else 0
        order_count = product_sales['order_id'].nunique()
    else:
        total_sold = 0
        current_stock = 0
        order_count = 0
    
    # Create product card with image
    col1, col2 = st.columns([1, 2])
    
    with col1:
        # Fetch and display product image by category
        with st.spinner("🖼️"):
            image_url = fetch_product_image_by_category(category, title)
            if image_url:
                img = load_image_from_url(image_url)
                if img:
                    st.image(img, caption=title, use_container_width=True)
                else:
                    st.image("https://via.placeholder.com/150x150?text=No+Image", 
                            caption="Placeholder", use_container_width=True)
            else:
                st.image("https://via.placeholder.com/150x150?text=No+Image", 
                        caption="No Image Available", use_container_width=True)
    
    with col2:
        st.markdown(f"**SKU:** `{sku}`")
        st.markdown(f"**Category:** {category}")
        
        # Display metrics in columns
        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("Sold", f"{total_sold:,.0f}")
        mcol2.metric("Stock", f"{current_stock:,.0f}")
        mcol3.metric("Orders", f"{order_count}")
    
    st.markdown("---")

def main():
    # Header
    st.markdown('<div class="main-header">📊 Product Launch Performance Analytics Dashboard</div>', 
                unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.image("https://via.placeholder.com/300x100/1E88E5/ffffff?text=Product+Analytics", 
                 width=True)
        
        st.markdown("## 📅 Date Selection")
        
        # Date inputs
        today = datetime.now()
        
        launch_date = st.date_input(
            "Product Launch Date",
            value=today - timedelta(days=5),
            max_value=today
        )
        
        col1, col2 = st.columns(2)
        with col1:
            analysis_start = st.date_input(
                "Analysis Start",
                value=launch_date,
                max_value=today
            )
        with col2:
            analysis_end = st.date_input(
                "Analysis End",
                value=today,
                min_value=analysis_start,
                max_value=today
            )
        
        st.markdown("---")
        
        # Start Analysis Button
        start_analysis = st.button("🚀 Start Analysis", type="primary", use_container_width=True)
        
        if start_analysis:
            st.session_state['analysis_started'] = True
        
        st.markdown("---")
        st.markdown("### ℹ️ About")
        st.info(
            "This dashboard tracks product performance after launch, "
            "analyzing sales metrics and product details."
        )
    
    # Initialize session state
    if 'analysis_started' not in st.session_state:
        st.session_state['analysis_started'] = False
    
    # Main content area - Only show if analysis started
    if st.session_state['analysis_started']:
        try:
            # Format dates for API
            launch_date_str = f"{launch_date}T00:00:00Z"
            order_start_str = f"{analysis_start}T00:00:00Z"
            order_end_str = f"{analysis_end}T23:59:59Z"
            
            # Load data with progress indicators
            with st.spinner("📥 Fetching product data..."):
                products_df = get_products(launch_date_str)
            
            with st.spinner("📥 Fetching inventory data..."):
                inventory_df = get_inventory_data(order_start_str, order_end_str)
            
            # Calculate metrics
            metrics = calculate_metrics(products_df, inventory_df, launch_date_str)
            
            # KPI Metrics Row
            st.markdown("## 📈 Key Performance Indicators")
            
            # First row of metrics
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown("""
                <div class="metric-card">
                    <div class="metric-value">{}</div>
                    <div class="metric-label">🚀 Products Launched</div>
                    <div class="metric-subtext">On selected date</div>
                </div>
                """.format(metrics['products_launched']), unsafe_allow_html=True)
            
            with col2:
                st.markdown("""
                <div class="metric-card">
                    <div class="metric-value">{}</div>
                    <div class="metric-label">📦 Categories</div>
                    <div class="metric-subtext">Unique product categories</div>
                </div>
                """.format(metrics['categories']), unsafe_allow_html=True)
            
            with col3:
                st.markdown("""
                <div class="metric-card">
                    <div class="metric-value">{} | {}</div>
                    <div class="metric-label">🔖 SKU Sold</div>
                    <div class="metric-subtext">New: {} SKU | Old: {} SKU</div>
                </div>
                """.format(
                    metrics['new_skus_sold'], 
                    metrics['old_skus_sold'],
                    metrics['new_skus_sold'],
                    metrics['old_skus_sold']
                ), unsafe_allow_html=True)
            
            with col4:
                st.markdown("""
                <div class="metric-card">
                    <div class="metric-value">{:,} | {:,}</div>
                    <div class="metric-label">📊 Quantity Sold</div>
                    <div class="metric-subtext">New: {:,} units | Old: {:,} units</div>
                </div>
                """.format(
                    metrics['new_qty_sold'], 
                    metrics['old_qty_sold'],
                    metrics['new_qty_sold'],
                    metrics['old_qty_sold']
                ), unsafe_allow_html=True)
            
            st.markdown("---")
            
            # Summary Table: Only new products with specified columns
            st.markdown("## 📋 New Products Sales Summary by Category")
            
            if not inventory_df.empty and not products_df.empty:
                # Get launch date for filtering
                launch_dt = pd.to_datetime(launch_date_str).date()
                
                # Filter for new products only (launched on selected date)
                new_products_df = inventory_df[
                    inventory_df['product_createdAt'].dt.date == launch_dt
                ].copy()
                
                if not new_products_df.empty:
                    # Create summary table with only the required columns
                    summary_df = new_products_df.groupby('product_category').agg({
                        'sku': 'nunique',  # Count of SKU Sold
                        'quantity': 'sum'   # Quantity sold
                    }).reset_index()
                    
                    # Rename columns as specified
                    summary_df.columns = ['Category', 'Count of SKU Sold', 'Quantity sold']
                    
                    # Sort by Category for better readability
                    summary_df = summary_df.sort_values('Category')
                    
                    # Display the table
                    st.dataframe(
                        summary_df,
                        use_container_width=True,
                        hide_index=True,
                        column_config={
                            "Category": "Category",
                            "Count of SKU Sold": st.column_config.NumberColumn(
                                "Count of SKU Sold", 
                                format="%d",
                                help="Number of unique SKUs sold"
                            ),
                            "Quantity sold": st.column_config.NumberColumn(
                                "Quantity sold", 
                                format="%d",
                                help="Total quantity sold"
                            )
                        }
                    )
                    
                    # Add a total row
                    total_skus = summary_df['Count of SKU Sold'].sum()
                    total_quantity = summary_df['Quantity sold'].sum()
                    
                    st.markdown(f"""
                    <div style="text-align: right; padding: 1rem; background: #f0f2f6; border-radius: 5px; margin-top: 1rem;">
                        <strong>Total:</strong> {total_skus} SKUs | {total_quantity:,.0f} units sold
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Visual representation for new products only
                    fig_summary = px.bar(
                        summary_df,
                        x='Category',
                        y=['Count of SKU Sold', 'Quantity sold'],
                        title='New Products Sales by Category',
                        barmode='group',
                        labels={'value': 'Count', 'variable': 'Metric'}
                    )
                    st.plotly_chart(fig_summary, use_container_width=True)
                else:
                    st.warning("No new products were sold in the selected period.")
            else:
                st.warning("No sales data available for the selected period.")
            
            st.markdown("---")
            
            # Product Details by Category - No nested dropdown
            st.markdown("## 📦 Product Details by Category")
            
            if not products_df.empty and not inventory_df.empty:
                # Get unique categories from launched products
                launch_dt = pd.to_datetime(launch_date_str).date()
                categories = products_df['productType'].unique().tolist()
                
                if categories:
                    # Category selection dropdown
                    selected_category = st.selectbox(
                        "Choose a product category to view details:",
                        options=categories
                    )
                    
                    if selected_category:
                        st.markdown(f"### Products in {selected_category}")
                        
                        # Get all products in this category (no further dropdown)
                        category_products = inventory_df[
                            (inventory_df['product_category'] == selected_category) &
                            (inventory_df['product_createdAt'].dt.date == launch_dt)
                        ][['sku', 'title']].drop_duplicates()
                        
                        if not category_products.empty:
                            # Display all products in the category as cards
                            for _, product in category_products.iterrows():
                                display_product_card(product, inventory_df, selected_category)
                        else:
                            st.info(f"No products found in category: {selected_category}")
                else:
                    st.warning("No categories available for the selected launch date.")
            else:
                st.warning("No product data available.")
        
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            st.exception(e)
    
    else:
        # Welcome message when analysis hasn't started
        st.markdown("""
        <div style="text-align: center; padding: 3rem;">
            <h2>👋 Welcome to Product Launch Performance Dashboard</h2>
            <p style="color: #666; font-size: 1.2rem; margin: 2rem;">
                Select dates from the sidebar and click "Start Analysis" to begin.
            </p>
            <div style="background: #f8f9fa; padding: 2rem; border-radius: 10px;">
                <h4>📊 What you can analyze:</h4>
                <ul style="list-style: none; padding: 0;">
                    <li>✅ Product launch performance metrics</li>
                    <li>✅ Category-wise new products sales breakdown</li>
                    <li>✅ Individual product details by category with images</li>
                    <li>✅ All products displayed within selected category</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
