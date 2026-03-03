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
import hashlib
import concurrent.futures
from functools import lru_cache
import time
import threading

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
    .pagination-controls {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: 1rem;
        margin: 2rem 0;
        padding: 1rem;
        background: #f8f9fa;
        border-radius: 10px;
    }
    .pagination-info {
        font-size: 1rem;
        color: #666;
        font-weight: 500;
    }
    .image-container {
        position: relative;
        width: 100%;
        padding-top: 100%; /* 1:1 Aspect Ratio */
        overflow: hidden;
        border-radius: 10px;
        background: #f0f2f6;
    }
    .image-container img {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
    }
    .loading-placeholder {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        background: #f0f2f6;
        color: #666;
        font-size: 0.9rem;
    }
    </style>
""", unsafe_allow_html=True)

# Initialize a thread-local cache for images
_image_cache = {}
_cache_lock = threading.Lock()

class ImageCache:
    """Thread-safe image cache with size limit"""
    def __init__(self, max_size=100):
        self.cache = {}
        self.max_size = max_size
        self.lock = threading.Lock()
    
    def get(self, key):
        with self.lock:
            return self.cache.get(key)
    
    def set(self, key, value):
        with self.lock:
            if len(self.cache) >= self.max_size:
                # Remove oldest item (simple FIFO)
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
            self.cache[key] = value

# Global image cache
image_cache = ImageCache(max_size=200)

# Helper function to generate a secure session token
def get_auth_token():
    env_email = os.getenv("ADMIN_EMAIL", "")
    env_password = os.getenv("ADMIN_PASSWORD", "")
    return hashlib.sha256(f"{env_email}::{env_password}".encode()).hexdigest()

def init_credentials():
    """Initialize Azure credentials"""
    return {
        "client_id": os.getenv("AZURE_CLIENT_ID"),
        "client_secret": os.getenv("AZURE_CLIENT_SECRET"),
        "tenant_id": os.getenv("AZURE_TENANT_ID"),
        "endpoint": os.getenv("FABRIC_ENDPOINT"),
        "shopify_endpoint": os.getenv("SHOPIFY_ENDPOINT"),
        "shopify_token": os.getenv("SHOPIFY_ACCESS_TOKEN")
    }

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

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_product_images_batch(category, product_titles):
    """
    Fetch multiple product images in a single batch API call
    """
    if not product_titles:
        return {}
    
    try:
        creds = init_credentials()
        
        # Build a more efficient query to get multiple products at once
        # Create a search query that combines all titles
        title_queries = [f'title:"{title}"' for title in product_titles[:10]]  # Limit to 10 per query
        combined_query = f"product_type:{category} AND ({' OR '.join(title_queries)})"
        
        graphql_query = """
        query getProductsBatch($query: String!) {
          products(first: 25, query: $query) {
            edges {
              node {
                title
                images(first: 1) {
                  edges {
                    node {
                      url
                    }
                  }
                }
                variants(first: 1) {
                  edges {
                    node {
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
            json={"query": graphql_query, "variables": {"query": combined_query}},
            timeout=15
        )

        response.raise_for_status()
        data = response.json()

        if "errors" in data or not data.get("data", {}).get("products", {}).get("edges"):
            return {}

        # Map titles to image URLs
        image_map = {}
        for product in data["data"]["products"]["edges"]:
            node = product["node"]
            title = node["title"]
            
            # Try to get image from variants first
            if node.get("variants", {}).get("edges"):
                for variant in node["variants"]["edges"]:
                    if variant["node"].get("image") and variant["node"]["image"].get("url"):
                        image_map[title] = variant["node"]["image"]["url"]
                        break
            
            # If no variant image, try product images
            if title not in image_map and node.get("images", {}).get("edges"):
                image_map[title] = node["images"]["edges"][0]["node"]["url"]
        
        return image_map

    except Exception as e:
        return {}

def load_image_from_url_optimized(url, max_size=(300, 300)):
    """Load image from URL with size optimization"""
    cache_key = f"{url}_{max_size}"
    
    # Check memory cache first
    cached_img = image_cache.get(cache_key)
    if cached_img:
        return cached_img
    
    try:
        # Add timeout and stream for better performance
        response = requests.get(url, timeout=5, stream=True)
        response.raise_for_status()
        
        # Load image
        img = Image.open(BytesIO(response.content))
        
        # Optimize image size
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Resize if larger than max_size
        if img.size[0] > max_size[0] or img.size[1] > max_size[1]:
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Cache the optimized image
        image_cache.set(cache_key, img)
        
        return img
    except:
        return None

def get_products(product_created_date, comparison_type="EQUALS"):
    """
    Fetch products launched on or before a specific date.
    comparison_type: "EQUALS" or "BEFORE"
    """
    try:
        creds = init_credentials()
        headers = get_headers(creds)
        if not headers: return pd.DataFrame()
        
        query = """
        query GetProducts($date: DateTime, $type: String) {
            executesp_products_new(ProductCreatedDate: $date, ComparisonType: $type) {
                product_id
                sku
                productType
                product_created
            }
        }
        """
        variables = {"date": product_created_date, "type": comparison_type}
        
        response = requests.post(
            creds["endpoint"],
            headers=headers,
            json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        items = response.json().get("data", {}).get("executesp_products_new", [])
        
        return pd.DataFrame(items) if items else pd.DataFrame(columns=["product_id", "sku", "productType", "product_created"])
        
    except Exception as e:
        st.error(f"Error loading products: {e}")
        return pd.DataFrame()

def get_inventory_data(order_start, order_end, product_start=None, product_end=None, categories=None):
    """
    Fetch inventory and sales data with optional product age and category filters.
    """
    try:
        creds = init_credentials()
        headers = get_headers(creds)
        if not headers: return pd.DataFrame()

        category_str = ",".join(categories) if isinstance(categories, list) else categories
        
        query = """
        query GetInventory(
            $oStart: DateTime, $oEnd: DateTime, 
            $pStart: DateTime, $pEnd: DateTime, 
            $cats: String
        ) {
            executesp_inventory_new(
                OrderStartDate: $oStart
                OrderEndDate: $oEnd
                ProductStartDate: $pStart
                ProductEndDate: $pEnd
                ProductCategories: $cats
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
            "oStart": order_start,
            "oEnd": order_end,
            "pStart": product_start,
            "pEnd": product_end,
            "cats": category_str
        }
        
        response = requests.post(
            creds["endpoint"],
            headers=headers,
            json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        items = response.json().get("data", {}).get("executesp_inventory_new", [])
        
        if not items:
            return pd.DataFrame()
        
        df = pd.DataFrame(items)
        
        if 'totalInventory' in df.columns:
            df['totalInventory'] = df['totalInventory'].apply(lambda x: max(x, 0) if pd.notna(x) else 0)
        
        for col in ['product_createdAt', 'order_createdAt']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        if 'quantity' in df.columns:
            df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0)
            
        return df
        
    except Exception as e:
        st.error(f"Error loading inventory: {e}")
        return pd.DataFrame()

def calculate_metrics(launch_df, sales_df, launch_date):
    """Calculate all required metrics"""
    metrics = {}
    
    metrics['products_launched'] = len(launch_df) if not launch_df.empty else 0
    categories_launched = launch_df['productType'].unique().tolist() if not launch_df.empty else []
    metrics['categories'] = len(categories_launched)
    
    if not sales_df.empty and not launch_df.empty:
        launch_dt = pd.to_datetime(launch_date).date()
        
        new_products = sales_df[sales_df['product_createdAt'].dt.date == launch_dt]
        new_skus_sold = new_products['sku'].nunique() if not new_products.empty else 0
        new_products_qty = new_products['quantity'].sum() if not new_products.empty else 0
        
        old_products = sales_df[
            (sales_df['product_createdAt'].dt.date < launch_dt) & 
            (sales_df['product_category'].isin(categories_launched))
        ]
        old_skus_sold = old_products['sku'].nunique() if not old_products.empty else 0
        old_products_qty = old_products['quantity'].sum() if not old_products.empty else 0
        
        metrics['new_skus_sold'] = new_skus_sold
        metrics['old_skus_sold'] = old_skus_sold
        metrics['new_qty_sold'] = int(new_products_qty)
        metrics['old_qty_sold'] = int(old_products_qty)
    else:
        metrics['new_skus_sold'] = 0
        metrics['old_skus_sold'] = 0
        metrics['new_qty_sold'] = 0
        metrics['old_qty_sold'] = 0
    
    return metrics

def display_product_card_optimized(product_data, inventory_data, category, image_url=None):
    """Display a single product card with optimized image loading"""
    sku = product_data['sku']
    title = product_data['title']
    
    product_sales = inventory_data[inventory_data['sku'] == sku]
    
    if not product_sales.empty:
        total_sold = product_sales['quantity'].sum()
        current_stock = product_sales['totalInventory'].iloc[0] if 'totalInventory' in product_sales.columns else 0
        order_count = product_sales['order_id'].nunique()
    else:
        total_sold = 0
        current_stock = 0
        order_count = 0
    
    with st.container(border=True):        
        if image_url:
            try:
                img = load_image_from_url_optimized(image_url)
                if img:
                    st.image(img, width='stretch')
                else:
                    st.markdown('<div class="loading-placeholder">📷 No Image</div>', unsafe_allow_html=True)
            except:
                st.markdown('<div class="loading-placeholder">📷 Error</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="loading-placeholder">📷 No Image</div>', unsafe_allow_html=True)
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown(f"**{title}**")
        st.caption(f"SKU: `{sku}`")
        
        mcol1, mcol2, mcol3 = st.columns(3)
        mcol1.metric("Sold", f"{total_sold:,.0f}")
        mcol2.metric("Stock", f"{current_stock:,.0f}")
        mcol3.metric("Orders", f"{order_count}")

def display_product_grid_with_pagination_optimized(products_df, inventory_df, category, section_type, products_per_page=10):
    """
    Optimized version with batch image loading and lazy loading
    """
    if products_df.empty:
        st.info(f"No {section_type} products found in this classification.")
        return

    # Get unique products
    product_list = products_df[['sku', 'title']].drop_duplicates().to_dict('records')
    total_products = len(product_list)
    
    # Initialize pagination state
    pagination_key = f"pagination_{category}_{section_type}"
    if pagination_key not in st.session_state:
        st.session_state[pagination_key] = 0
    
    # Calculate pagination
    start_idx = st.session_state[pagination_key] * products_per_page
    end_idx = min(start_idx + products_per_page, total_products)
    
    # Display current page info
    st.markdown(f"<p style='text-align: center; color: #666;'>Showing {start_idx + 1}-{end_idx} of {total_products} {section_type} products</p>", unsafe_allow_html=True)
    
    # Get current page products
    current_page_products = product_list[start_idx:end_idx]
    
    # Batch load images for current page
    with st.spinner("🖼️ Loading images..."):
        product_titles = [p['title'] for p in current_page_products]
        image_map = fetch_product_images_batch(category, product_titles)
    
    # Display products in grid
    for i in range(0, len(current_page_products), 3):
        cols = st.columns(3)
        chunk = current_page_products[i:i+3]
        
        for j, product_data in enumerate(chunk):
            with cols[j]:
                image_url = image_map.get(product_data['title'])
                display_product_card_optimized(product_data, inventory_df, category, image_url)
    
    # Pagination controls
    col1, col2, col3, col4, col5 = st.columns([1, 1, 2, 1, 1])
    
    with col2:
        if st.button("◀ Previous", key=f"prev_{category}_{section_type}", disabled=st.session_state[pagination_key] == 0):
            st.session_state[pagination_key] -= 1
            st.rerun()
    
    with col3:
        st.markdown(f"<p style='text-align: center;'>Page {st.session_state[pagination_key] + 1} of {(total_products - 1) // products_per_page + 1}</p>", unsafe_allow_html=True)
    
    with col4:
        if st.button("Next ▶", key=f"next_{category}_{section_type}", disabled=end_idx >= total_products):
            st.session_state[pagination_key] += 1
            st.rerun()
    

def main():
    expected_token = get_auth_token()

    # Session Management
    if st.query_params.get("session") == expected_token:
        st.session_state['is_logged_in'] = True
    elif 'is_logged_in' not in st.session_state:
        st.session_state['is_logged_in'] = False

    if 'analysis_started' not in st.session_state:
        st.session_state['analysis_started'] = False

    # Header
    st.markdown('<div class="main-header">📊 Product Launch Performance Analytics Dashboard</div>', 
                unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.image("https://placehold.co/300x100/1E88E5/FFFFFF?text=Prashanti+Sarees", width='stretch')

        # Login Logic
        if not st.session_state['is_logged_in']:
            st.markdown("## 🔐 Admin Login")
            with st.form("login_form"):
                email_input = st.text_input("Email")
                password_input = st.text_input("Password", type="password")
                submit_button = st.form_submit_button("Login", type="primary", width='stretch')
                
                if submit_button:
                    env_email = os.getenv("ADMIN_EMAIL")
                    env_password = os.getenv("ADMIN_PASSWORD")
                    
                    if email_input == env_email and password_input == env_password:
                        st.session_state['is_logged_in'] = True
                        st.query_params["session"] = expected_token
                        st.rerun() 
                    else:
                        st.error("❌ Invalid email or password")
        
        # Logged In Controls
        else:
            st.success("✅ Logged in successfully")
            st.markdown("## 📅 Date Selection")
            
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
            
            # Add products per page selector
            products_per_page = st.selectbox(
                "Products per page",
                options=[6, 9, 12, 15, 18, 21, 24],
                index=1  # Default to 9 for faster loading
            )
            
            # Option to disable images for faster loading
            disable_images = st.checkbox("Disable images for faster loading", value=False)
            
            start_analysis = st.button("🚀 Start Analysis", type="primary", width='stretch')
            
            if start_analysis:
                st.session_state['analysis_started'] = True
            
            st.markdown("---")
            st.markdown("### ℹ️ About")
            st.info(
                "This dashboard tracks product performance after launch, "
                "analyzing sales metrics and product details."
            )
            
            st.markdown("---")
            if st.button("🚪 Logout", width='stretch'):
                st.session_state['is_logged_in'] = False
                st.session_state['analysis_started'] = False
                if "session" in st.query_params:
                    del st.query_params["session"]
                st.rerun()
    
    # Main content area - Authentication Gate
    if not st.session_state['is_logged_in']:
        st.markdown("""
        <div style="text-align: center; padding: 1rem;">
            <p style="color: #666; font-size: 1.2rem; margin: 2rem;">
                Please <b>log in</b> from the sidebar to access the dashboard.
            </p>
            <div style="background: #f8f9fa; padding: 2rem; border-radius: 10px; display: inline-block; text-align: left; min-width: 400px;">
                <h4 style="text-align: center;">📊 What you can analyze:</h4>
                <ul style="list-style: none; padding: 0; margin: 0 auto; display: inline-block;">
                    <li style="margin-bottom: 0.5rem;">✅ Product launch performance metrics</li>
                    <li style="margin-bottom: 0.5rem;">✅ Category-wise new products sales breakdown</li>
                    <li style="margin-bottom: 0.5rem;">✅ Individual product details by category with images</li>
                    <li style="margin-bottom: 0.5rem;">✅ All products displayed within selected category</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    # Logged In, pending analysis start
    if not st.session_state['analysis_started']:
       st.markdown("""
        <div style="text-align: center; padding: 1rem;">
            <p style="color: #666; font-size: 1.2rem; margin: 2rem;">
                Select dates from the sidebar and click "Start Analysis" to begin.
            </p>
            <div style="background: #f8f9fa; padding: 2rem; border-radius: 10px; display: inline-block; text-align: left; min-width: 400px;">
                <h4 style="text-align: center;">📊 What you can analyze:</h4>
                <ul style="list-style: none; padding: 0; margin: 0 auto; display: inline-block;">
                    <li style="margin-bottom: 0.5rem;">✅ Product launch performance metrics</li>
                    <li style="margin-bottom: 0.5rem;">✅ Category-wise new products sales breakdown</li>
                    <li style="margin-bottom: 0.5rem;">✅ Individual product details by category with images</li>
                    <li style="margin-bottom: 0.5rem;">✅ All products displayed within selected category</li>
                </ul>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Logged In and Analysis Started
    if st.session_state['analysis_started']:
        try:
            launch_date_str = f"{launch_date}T00:00:00Z"
            order_start_str = f"{analysis_start}T00:00:00Z"
            order_end_str = f"{analysis_end}T23:59:59Z"
            today_str = f"{datetime.now().date()}T23:59:59Z"
            
            with st.spinner("📥 Fetching product data..."):
                products_df = get_products(launch_date_str, comparison_type="EQUALS")
                launch_categories = products_df['productType'].unique().tolist() if not products_df.empty else []

            with st.spinner("📥 Fetching filtered inventory data..."):
                inventory_df = get_inventory_data(order_start_str, order_end_str)
                
                all_time_sales = pd.DataFrame()
                if launch_categories:
                    all_time_sales = get_inventory_data(
                        order_start=None, 
                        order_end=today_str, 
                        categories=launch_categories
                    )
            
            metrics = calculate_metrics(products_df, inventory_df, launch_date_str)
            
            st.markdown("## 📈 Key Performance Indicators")
            
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
            
            # Helper function for Initial Quantity logic
            def get_initial_qty_summary(sales_all_df, product_filter_df):
                if sales_all_df.empty or product_filter_df.empty:
                    return pd.DataFrame(columns=['product_category', 'sku_initial'])
                
                relevant_skus = product_filter_df['sku'].unique()
                sku_subset = sales_all_df[sales_all_df['sku'].isin(relevant_skus)]
                
                if sku_subset.empty:
                     return pd.DataFrame(columns=['product_category', 'sku_initial'])

                sku_level = sku_subset.groupby(['product_category', 'sku']).agg({
                    'quantity': 'sum',
                    'totalInventory': 'last'
                }).reset_index()
                
                sku_level['sku_initial'] = sku_level['quantity'] + sku_level['totalInventory']
                
                return sku_level.groupby('product_category')['sku_initial'].sum().reset_index()

            # --- START DATA PROCESSING ---
            if not inventory_df.empty and not products_df.empty:
                launch_dt = pd.to_datetime(launch_date_str).date()
                
                # Logic for New Products
                new_products_df = inventory_df[inventory_df['product_createdAt'].dt.date == launch_dt].copy()
                
                # Logic for Old Products
                old_products_df = inventory_df[
                    (inventory_df['product_createdAt'].dt.date < launch_dt) & 
                    (inventory_df['product_category'].isin(launch_categories))
                ].copy()
                
                # Build Summaries
                new_summary_df = new_products_df.groupby('product_category').agg({
                    'sku': 'nunique', 'quantity': 'sum'
                }).reset_index().rename(columns={'sku': 'Count of New SKU Sold', 'quantity': 'New Quantity sold'})

                old_summary_df = old_products_df.groupby('product_category').agg({
                    'sku': 'nunique', 'quantity': 'sum'
                }).reset_index().rename(columns={'sku': 'Count of Old SKU Sold', 'quantity': 'Old Quantity sold'})

                new_init_df = get_initial_qty_summary(all_time_sales, new_products_df).rename(columns={'sku_initial': 'Initial Qty New'})
                old_init_df = get_initial_qty_summary(all_time_sales, old_products_df).rename(columns={'sku_initial': 'Initial Qty Old'})

                # Final Merge for the Summary Table
                summary_df = pd.merge(new_summary_df, old_summary_df, on='product_category', how='outer')
                summary_df = pd.merge(summary_df, new_init_df, on='product_category', how='outer')
                summary_df = pd.merge(summary_df, old_init_df, on='product_category', how='outer').fillna(0)
                
                # Calculate Sales Percentages
                summary_df['Sales % of New SKUs'] = (summary_df['New Quantity sold'] / summary_df['Initial Qty New'] * 100).fillna(0)
                summary_df['Sales % of Old SKUs'] = (summary_df['Old Quantity sold'] / summary_df['Initial Qty Old'] * 100).fillna(0)

                summary_df.rename(columns={'product_category': 'Categories'}, inplace=True)

                column_order = [
                    'Categories', 
                    'Count of New SKU Sold', 'New Quantity sold', 'Initial Qty New', 'Sales % of New SKUs',
                    'Count of Old SKU Sold', 'Old Quantity sold', 'Initial Qty Old', 'Sales % of Old SKUs'
                ]
                summary_df = summary_df[column_order]
                
                st.markdown("## 📋 New Products Sales Summary by Category")
                
                st.dataframe(
                    summary_df,
                    width='stretch',
                    hide_index=True,
                    column_config={
                        "Categories": "Category",
                        "Initial Qty New": st.column_config.NumberColumn("Initial Qty (New)", format="%d"),
                        "New Quantity sold": st.column_config.NumberColumn("New Qty Sold", format="%d"),
                        "Sales % of New SKUs": st.column_config.NumberColumn("Sales % (New)", format="%.2f%%"),
                        "Initial Qty Old": st.column_config.NumberColumn("Initial Qty (Old)", format="%d"),
                        "Old Quantity sold": st.column_config.NumberColumn("Old Qty Sold", format="%d"),
                        "Sales % of Old SKUs": st.column_config.NumberColumn("Sales % (Old)", format="%.2f%%"),
                    }
                )
                    
                total_new_skus = summary_df['Count of New SKU Sold'].sum()
                total_new_qty = summary_df['New Quantity sold'].sum()
                total_old_skus = summary_df['Count of Old SKU Sold'].sum()
                total_old_qty = summary_df['Old Quantity sold'].sum()
                
                st.markdown(f"""
                <div style="text-align: right; padding: 1rem; background: #f0f2f6; border-radius: 5px; margin-top: 1rem;">
                    <strong>New Products:</strong> {total_new_skus} SKUs | {total_new_qty:,.0f} units sold<br>
                    <strong>Existing Products:</strong> {total_old_skus} SKUs | {total_old_qty:,.0f} units sold
                </div>
                """, unsafe_allow_html=True)
                
                # --- CHARTS ---
                fig_summary = go.Figure()
                fig_summary.add_trace(go.Bar(
                    name='New SKUs',
                    x=summary_df['Categories'],
                    y=summary_df['Count of New SKU Sold'],
                    marker_color='#1E88E5'
                ))
                fig_summary.add_trace(go.Bar(
                    name='Existing SKUs',
                    x=summary_df['Categories'],
                    y=summary_df['Count of Old SKU Sold'],
                    marker_color='#FFA726'
                ))
                
                fig_summary.update_layout(
                    title='SKU Count Comparison by Category',
                    barmode='group',
                    xaxis_title='Category',
                    yaxis_title='Number of SKUs',
                    hovermode='x unified'
                )
                st.plotly_chart(fig_summary, width='stretch')
                
                fig_qty = go.Figure()
                fig_qty.add_trace(go.Bar(
                    name='New Quantity',
                    x=summary_df['Categories'],
                    y=summary_df['New Quantity sold'],
                    marker_color='#1E88E5'
                ))
                fig_qty.add_trace(go.Bar(
                    name='Existing Quantity',
                    x=summary_df['Categories'],
                    y=summary_df['Old Quantity sold'],
                    marker_color='#FFA726'
                ))
                
                fig_qty.update_layout(
                    title='Quantity Sold Comparison by Category',
                    barmode='group',
                    xaxis_title='Category',
                    yaxis_title='Quantity Sold',
                    hovermode='x unified'
                )
                st.plotly_chart(fig_qty, width='stretch')
            
                st.markdown("## 📦 Product Details by Category")
                
                if not products_df.empty and not inventory_df.empty:
                    launch_dt = pd.to_datetime(launch_date_str).date()
                    categories = products_df['productType'].unique().tolist()
                    
                    if categories:
                        selected_category = st.selectbox(
                            "Choose a product category to view details:",
                            options=categories
                        )
                        
                        if selected_category:
                            st.markdown(f"### Visual Directory: {selected_category}")
                            
                            category_products = inventory_df[
                                inventory_df['product_category'] == selected_category
                            ]
                            
                            new_cat_products = category_products[
                                category_products['product_createdAt'].dt.date == launch_dt
                            ]
                            old_cat_products = category_products[
                                category_products['product_createdAt'].dt.date < launch_dt
                            ]
                            
                            st.markdown("#### ✨ Newly Launched Products")
                            if disable_images:
                                # Simple version without images for maximum speed
                                st.dataframe(new_cat_products[['sku', 'title', 'quantity', 'totalInventory']])
                            else:
                                display_product_grid_with_pagination_optimized(
                                    new_cat_products, 
                                    inventory_df, 
                                    selected_category, 
                                    "new",
                                    products_per_page
                                )
                            
                            st.markdown("---")
                            st.markdown("#### 🕰️ Legacy / Existing Products")
                            if disable_images:
                                st.dataframe(old_cat_products[['sku', 'title', 'quantity', 'totalInventory']])
                            else:
                                display_product_grid_with_pagination_optimized(
                                    old_cat_products, 
                                    inventory_df, 
                                    selected_category, 
                                    "old",
                                    products_per_page
                                )
                else:
                    st.warning("No categories available for the selected launch date.")
            else:
                st.warning("No product data available.")
        
        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            st.exception(e)

if __name__ == "__main__":
    main()
