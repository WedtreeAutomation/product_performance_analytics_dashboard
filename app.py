import streamlit as st
import pandas as pd
import requests
import numpy as np
from azure.identity import ClientSecretCredential
import os
from dotenv import load_dotenv
from datetime import date, datetime
import plotly.express as px
import plotly.graph_objects as go

# =========================
# App Config & UI Setup
# =========================
st.set_page_config(
    page_title="Product Performance Analytics", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for enhanced styling
st.markdown("""
    <style>
    /* Main container styling */
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    
    /* Metric cards */
    .metric-card {
        background: white;
        padding: 1.5rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: transform 0.3s ease;
        border-left: 5px solid #667eea;
    }
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.15);
    }
    
    /* Section headers */
    .section-header {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1rem 2rem;
        border-radius: 10px;
        margin: 2rem 0 1rem 0;
        border-left: 8px solid #667eea;
        font-weight: 600;
    }
    
    /* Dataframe styling */
    .dataframe-container {
        background: white;
        padding: 1rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin: 1rem 0;
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div > div {
        background-image: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    }
    
    /* Button styling */
    .stButton > button {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        padding: 0.75rem 2rem;
        font-weight: 600;
        border-radius: 10px;
        transition: all 0.3s ease;
    }
    .stButton > button:hover {
        transform: scale(1.05);
        box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
    }
    
    /* Sidebar styling */
    .css-1d391kg {
        background: linear-gradient(180deg, #f8f9fa 0%, #e9ecef 100%);
    }
    
    /* Info boxes */
    .info-box {
        background: #e3f2fd;
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #2196f3;
        margin: 1rem 0;
    }
    </style>
""", unsafe_allow_html=True)

# =========================
# Header Section
# =========================
st.markdown("""
    <div class="main-header">
        <h1 style="font-size: 3rem; margin-bottom: 0.5rem;">📊 Product Performance Analytics</h1>
        <p style="font-size: 1.2rem; opacity: 0.9;">Unlock insights into your product portfolio with intelligent sales tracking</p>
    </div>
""", unsafe_allow_html=True)

# =========================
# Load Environment Variables Safely
# =========================
load_dotenv()

CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "").strip().strip("'").strip('"')
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "").strip().strip("'").strip('"')
TENANT_ID = os.getenv("AZURE_TENANT_ID", "").strip().strip("'").strip('"')
FABRIC_ENDPOINT = os.getenv("FABRIC_ENDPOINT", "").strip().strip("'").strip('"')
SHOPIFY_ENDPOINT = os.getenv("SHOPIFY_ENDPOINT", "").strip().strip("'").strip('"')
SHOPIFY_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "").strip().strip("'").strip('"')

if not all([CLIENT_ID, CLIENT_SECRET, TENANT_ID, FABRIC_ENDPOINT, SHOPIFY_TOKEN]):
    st.error("⚠️ Missing credentials in `.env` file.")
    st.stop()

# =========================
# Helper Functions
# =========================
@st.cache_data(ttl=3600, show_spinner=False)
def get_fabric_headers():
    credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
    scope = 'https://api.fabric.microsoft.com/.default'
    token = credential.get_token(scope).token
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

def get_processed_inventory(order_start, order_end, product_start, product_end, period):
    query = """
    query GetInventory($orderStart: DateTime, $orderEnd: DateTime, $productStart: DateTime, $productEnd: DateTime) {
      executesp_inventory(OrderStartDate: $orderStart, OrderEndDate: $orderEnd, ProductStartDate: $productStart, ProductEndDate: $productEnd) {
        sku
        displayName
        inventoryQuantity
        quantity
        status
      }
    }
    """
    try:
        variables = {"orderStart": order_start, "orderEnd": order_end, "productStart": product_start, "productEnd": product_end}
        response = requests.post(FABRIC_ENDPOINT, headers=get_fabric_headers(), json={"query": query, "variables": variables})
        response.raise_for_status()
        
        items = response.json().get("data", {}).get("executesp_inventory", [])
        if not items:
            return pd.DataFrame(columns=['sku', 'displayName', f'qty_{period}'])

        df = pd.DataFrame(items)
        df['calc_val'] = np.where(df['status'] == 'SUCCESS', df['quantity'], 0) + df['inventoryQuantity']
        return df.groupby(['sku', 'displayName'], as_index=False).agg(**{f'qty_{period}': ('calc_val', 'sum')})
        
    except Exception as e:
        st.error(f"Error loading {period} data: {e}")
        return pd.DataFrame()

def get_shopify_product_data(sku_list):
    query = """
    query getProductBySKU($query: String!) {
      productVariants(first: 1, query: $query) {
        edges {
          node {
            sku
            product {
              productType
              images(first: 1) { nodes { originalSrc } }
            }
          }
        }
      }
    }
    """
    shopify_headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": SHOPIFY_TOKEN}
    results = []
    
    progress_bar = st.progress(0, text="🔄 Syncing with Shopify...")
    status_text = st.empty()
    
    for i, sku in enumerate(sku_list):
        try:
            status_text.text(f"📦 Fetching data for SKU: {sku}")
            response = requests.post(SHOPIFY_ENDPOINT, headers=shopify_headers, json={"query": query, "variables": {"query": f"sku:{sku}"}})
            response.raise_for_status()
            edges = response.json().get("data", {}).get("productVariants", {}).get("edges", [])
            
            image_url = None
            product_type = "Uncategorized"
            
            if edges:
                prod_node = edges[0]["node"]["product"]
                
                if prod_node.get("images", {}).get("nodes"):
                    image_url = prod_node["images"]["nodes"][0]["originalSrc"]
                
                fetched_type = prod_node.get("productType")
                if fetched_type:
                    product_type = fetched_type
            
            results.append({"sku": sku, "imageUrl": image_url, "collectionName": product_type})

        except:
            results.append({"sku": sku, "imageUrl": None, "collectionName": "Uncategorized"})
            
        progress_bar.progress((i + 1) / len(sku_list))
        
    progress_bar.empty()
    status_text.empty()
    return pd.DataFrame(results)

def create_performance_chart(df, title):
    fig = px.bar(
        df.head(10),
        x='collectionName',
        y='Collection_Sales_Percentage',
        title=title,
        color='Collection_Sales_Percentage',
        color_continuous_scale='Viridis',
        labels={'collectionName': 'Product Type', 'Collection_Sales_Percentage': 'Sales Performance (%)'}
    )
    fig.update_layout(
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        font_family="Arial",
        title_font_size=20,
        hoverlabel=dict(bgcolor="white", font_size=14),
        xaxis_tickangle=-45
    )
    fig.update_traces(marker_line_width=2, marker_line_color="white")
    return fig

# =========================
# Sidebar UI
# =========================
with st.sidebar:
    st.markdown("""
        <div style="text-align: center; padding: 1rem; background: white; border-radius: 15px; margin-bottom: 1rem;">
            <h3 style="color: #667eea;">⚙️ Analysis Controls</h3>
        </div>
    """, unsafe_allow_html=True)
    
    product_launch_date = st.date_input(
        "📅 Product Launch Date",
        value=None,
        format="DD-MM-YYYY",
        help="Select the date when products were launched"
    )
    
    analysis_end_date = st.date_input(
        "📊 Analysis Period End Date",
        value=None,
        format="DD-MM-YYYY",
        help="Select the end date for the analysis period"
    )
    
    st.markdown("""
        <div class="info-box">
            <strong>📌 Note:</strong> Base period automatically set to current date
        </div>
    """, unsafe_allow_html=True)
    
    st.divider()
    
    can_run = product_launch_date and analysis_end_date
    run_query = st.button("🚀 Launch Analysis", type="primary", use_container_width=True, disabled=not can_run)
    
    if not can_run:
        st.info("👆 Please select both dates to begin analysis")

# =========================
# Data Fetching Logic
# =========================
if run_query:
    with st.spinner("🔄 Initializing data pipeline..."):
        launch_start = product_launch_date.strftime("%Y-%m-%d") + "T00:00:00Z"
        launch_end = product_launch_date.strftime("%Y-%m-%d") + "T23:59:59Z"
        analysis_end = analysis_end_date.strftime("%Y-%m-%d") + "T23:59:59Z"
        current_date = date.today().strftime("%Y-%m-%d") + "T23:59:59Z"

        # Fetch data with professional terminology
        with st.status("📥 Fetching inventory data...", expanded=True) as status:
            st.write("⏳ Retrieving launch quantities...")
            df_launch = get_processed_inventory(launch_start, current_date, launch_start, launch_end, "launch")
            
            st.write("⏳ Retrieving analysis period sales...")
            df_analysis = get_processed_inventory(launch_start, analysis_end, launch_start, launch_end, "analysis")
            
            status.update(label="✅ Data retrieval complete!", state="complete")

    if df_launch.empty and df_analysis.empty:
        st.warning("⚠️ No data found for the selected dates. Please verify your date ranges.")
        st.stop()

    with st.spinner("🔄 Processing and enriching data..."):
        df_merged = pd.merge(df_launch, df_analysis, on=['sku', 'displayName'], how='outer').fillna(0)
        
        df_merged["sales_percentage"] = np.where(
            df_merged["qty_launch"] > 0,
            (df_merged["qty_analysis"] / df_merged["qty_launch"]) * 100,
            0.0
        ).round(2)

        sku_list = df_merged["sku"].dropna().unique().tolist()
        df_shopify = get_shopify_product_data(sku_list)
        
        df_final = df_merged.merge(df_shopify, on="sku", how="left")
        
        # Add performance categories
        df_final['performance_category'] = pd.cut(
            df_final['sales_percentage'],
            bins=[0, 25, 50, 75, 100],
            labels=['Low', 'Medium', 'High', 'Excellent']
        )
        
        st.session_state['df_master'] = df_final
        st.session_state['analysis_complete'] = True

# =========================
# Interactive Dashboard
# =========================
if 'df_master' in st.session_state:
    df_master = st.session_state['df_master']
    
    # Quick Stats Row
    st.markdown("### 📊 Key Performance Indicators")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("""
            <div class="metric-card">
                <h4 style="color: #666;">Total Products</h4>
                <h2 style="color: #667eea; margin: 0;">{}</h2>
                <p style="color: #999; font-size: 0.9rem;">Unique SKUs analyzed</p>
            </div>
        """.format(len(df_master['sku'].unique())), unsafe_allow_html=True)
    
    with col2:
        total_launch_qty = int(df_master['qty_launch'].sum())
        st.markdown("""
            <div class="metric-card">
                <h4 style="color: #666;">Total Launch Inventory</h4>
                <h2 style="color: #667eea; margin: 0;">{:,}</h2>
                <p style="color: #999; font-size: 0.9rem;">Units available at launch</p>
            </div>
        """.format(total_launch_qty), unsafe_allow_html=True)
    
    with col3:
        total_analysis_qty = int(df_master['qty_analysis'].sum())
        st.markdown("""
            <div class="metric-card">
                <h4 style="color: #666;">Period Sales Volume</h4>
                <h2 style="color: #667eea; margin: 0;">{:,}</h2>
                <p style="color: #999; font-size: 0.9rem;">Units sold in selected period</p>
            </div>
        """.format(total_analysis_qty), unsafe_allow_html=True)
    
    with col4:
        avg_performance = df_master['sales_percentage'].mean()
        st.markdown("""
            <div class="metric-card">
                <h4 style="color: #666;">Average Performance</h4>
                <h2 style="color: #667eea; margin: 0;">{:.1f}%</h2>
                <p style="color: #999; font-size: 0.9rem;">Sales vs launch inventory</p>
            </div>
        """.format(avg_performance), unsafe_allow_html=True)
    
    st.divider()
    
    # --- 1. Product Type Performance Analysis ---
    st.markdown("""
        <div class="section-header">
            <h3>🏷️ Product Category Performance</h3>
            <p style="color: #666; margin: 0;">Analysis of sales performance by product type</p>
        </div>
    """, unsafe_allow_html=True)
    
    df_clean = df_master[df_master['collectionName'].notna()]
    
    # Category statistics
    category_stats = df_clean.groupby("collectionName").agg(
        Launch_Inventory=('qty_launch', 'sum'),
        Period_Sales=('qty_analysis', 'sum'),
        Product_Count=('sku', 'nunique')
    ).reset_index()
    
    category_stats["Sales_Performance"] = np.where(
        category_stats["Launch_Inventory"] > 0,
        (category_stats["Period_Sales"] / category_stats["Launch_Inventory"]) * 100,
        0.0
    ).round(2)
    
    category_stats = category_stats.sort_values(by="Sales_Performance", ascending=False)
    
    # Visual layout for category performance
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.markdown('<div class="dataframe-container">', unsafe_allow_html=True)
        st.dataframe(
            category_stats,
            width='stretch',
            hide_index=True,
            column_config={
                "collectionName": st.column_config.TextColumn("Product Category", width="medium"),
                "Product_Count": st.column_config.NumberColumn("SKU Count", format="%d"),
                "Launch_Inventory": st.column_config.NumberColumn("Launch Qty", format="%d"),
                "Period_Sales": st.column_config.NumberColumn("Period Sales", format="%d"),
                "Sales_Performance": st.column_config.ProgressColumn(
                    "Performance (%)",
                    format="%.2f%%",
                    min_value=0,
                    max_value=100
                )
            }
        )
        st.markdown('</div>', unsafe_allow_html=True)
    
    with col2:
        # Performance distribution pie chart
        perf_dist = df_clean['performance_category'].value_counts().reset_index()
        perf_dist.columns = ['Category', 'Count']
        
        fig = px.pie(
            perf_dist,
            values='Count',
            names='Category',
            title='Performance Distribution',
            color_discrete_sequence=px.colors.sequential.Viridis_r,
            hole=0.4
        )
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            font_family="Arial",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
    
    st.divider()
    
    # --- 2. Drill Down Selection ---
    st.markdown("""
        <div class="section-header">
            <h3>🔍 Product Deep Dive</h3>
            <p style="color: #666; margin: 0;">Explore individual product performance within each category</p>
        </div>
    """, unsafe_allow_html=True)
    
    category_options = category_stats["collectionName"].unique().tolist()
    
    if category_options:
        # Add search/filter capability
        col1, col2 = st.columns([2, 1])
        with col1:
            selected_category = st.selectbox(
                "📋 Select a product category to explore:",
                options=category_options,
                index=0,
                help="Choose a category to view detailed product performance"
            )
        with col2:
            sort_option = st.selectbox(
                "🔽 Sort by:",
                options=["Performance (High to Low)", "Performance (Low to High)", "Product Name", "Sales Volume"]
            )
        
        if selected_category:
            # Filter products for selected category
            df_category_products = df_master[df_master["collectionName"] == selected_category].drop_duplicates(subset=['sku'])
            
            # Apply sorting
            if sort_option == "Performance (High to Low)":
                df_category_products = df_category_products.sort_values(by="sales_percentage", ascending=False)
            elif sort_option == "Performance (Low to High)":
                df_category_products = df_category_products.sort_values(by="sales_percentage", ascending=True)
            elif sort_option == "Product Name":
                df_category_products = df_category_products.sort_values(by="displayName", ascending=True)
            elif sort_option == "Sales Volume":
                df_category_products = df_category_products.sort_values(by="qty_analysis", ascending=False)
            
            # Category summary metrics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Products in Category", len(df_category_products))
            with col2:
                st.metric("Total Category Sales", f"{int(df_category_products['qty_analysis'].sum()):,}")
            with col3:
                avg_cat_perf = df_category_products['sales_percentage'].mean()
                st.metric("Avg Category Performance", f"{avg_cat_perf:.1f}%")
            with col4:
                top_performer = df_category_products.nlargest(1, 'sales_percentage')['displayName'].values[0]
                st.metric("Top Performer", top_performer[:20] + "..." if len(top_performer) > 20 else top_performer)
            
            st.markdown(f"<h4 style='margin-top: 1rem;'>📦 Products in '{selected_category}' ({len(df_category_products)} items)</h4>", unsafe_allow_html=True)
            
            # Product display columns
            display_cols = ["imageUrl", "sku", "displayName", "qty_launch", "qty_analysis", "sales_percentage"]
            df_display = df_category_products[display_cols]

            # Enhanced product display with images
            st.markdown('<div class="dataframe-container">', unsafe_allow_html=True)
            st.dataframe(
                df_display,
                width='stretch',
                hide_index=True,
                column_config={
                    "imageUrl": st.column_config.ImageColumn("📸 Product", width="small"),
                    "sku": st.column_config.TextColumn("SKU", width="small"),
                    "displayName": st.column_config.TextColumn("Product Name", width="large"),
                    "qty_launch": st.column_config.NumberColumn("Launch Qty", format="%d", width="small"),
                    "qty_analysis": st.column_config.NumberColumn("Period Sales", format="%d", width="small"),
                    "sales_percentage": st.column_config.ProgressColumn(
                        "Performance %",
                        format="%.2f%%",
                        min_value=0,
                        max_value=100,
                        width="medium"
                    )
                }
            )
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Export option
            csv = df_display.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Product Data (CSV)",
                data=csv,
                file_name=f"{selected_category}_products_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    else:
        st.info("No product categories found in the data.")

# Footer
st.markdown("""
    <div style="text-align: center; margin-top: 3rem; padding: 1rem; background: #f8f9fa; border-radius: 10px;">
        <p style="color: #666; font-size: 0.9rem;">
            📊 Product Performance Analytics Dashboard | Data refreshes automatically | 
            Last analysis: {}
        </p>
    </div>
""".format(datetime.now().strftime("%Y-%m-%d %H:%M")), unsafe_allow_html=True)
