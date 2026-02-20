import streamlit as st
import pandas as pd
import requests
import numpy as np
from azure.identity import ClientSecretCredential
import os
from dotenv import load_dotenv
from datetime import date, datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image
from io import BytesIO

# =========================
# App Config & UI Setup
# =========================
st.set_page_config(
    page_title="Product Performance Analytics Pro", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for enhanced styling
st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        color: white;
        text-align: center;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
    }
    
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
    
    .section-header {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 1rem 2rem;
        border-radius: 10px;
        margin: 2rem 0 1rem 0;
        border-left: 8px solid #667eea;
        font-weight: 600;
    }
    
    .product-image-fast {
        width: 100%;
        height: 200px;
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e8eb 100%);
        border-radius: 15px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: #999;
        font-size: 0.9rem;
        position: relative;
        overflow: hidden;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
    }
    
    .product-image-fast img {
        width: 100%;
        height: 100%;
        object-fit: cover;
        transition: transform 0.3s ease;
    }
    
    .product-image-fast:hover img {
        transform: scale(1.05);
    }
    
    .dataframe-container {
        background: white;
        padding: 1rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin: 1rem 0;
        overflow-x: auto;
    }
    
    .stProgress > div > div > div > div {
        background-image: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    }
    
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
    
    .info-box {
        background: #e3f2fd;
        padding: 1rem;
        border-radius: 10px;
        border-left: 5px solid #2196f3;
        margin: 1rem 0;
    }
    
    .badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
    }
    .badge-success {
        background: #e8f5e9;
        color: #2e7d32;
    }
    .badge-warning {
        background: #fff3e0;
        color: #f57c00;
    }
    </style>
""", unsafe_allow_html=True)

# =========================
# Header Section
# =========================
st.markdown("""
    <div class="main-header">
        <h1 style="font-size: 3rem; margin-bottom: 0.5rem;">📊 Product Performance Analytics Pro</h1>
        <p style="font-size: 1.2rem; opacity: 0.9;">Lightning-fast analytics with optimized image loading</p>
    </div>
""", unsafe_allow_html=True)

# =========================
# Load Environment Variables
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
# Caching Functions
# =========================
@st.cache_resource
def get_fabric_token():
    """Cache Fabric token"""
    try:
        credential = ClientSecretCredential(TENANT_ID, CLIENT_ID, CLIENT_SECRET)
        scope = 'https://api.fabric.microsoft.com/.default'
        token = credential.get_token(scope).token
        return token
    except Exception as e:
        st.error(f"Failed to authenticate with Fabric: {e}")
        return None

def get_fabric_headers():
    token = get_fabric_token()
    if token:
        return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_single_product_image(sku):
    """Fetch image for a single SKU using the modernized Shopify GraphQL structure"""
    clean_sku = str(sku).strip()
    query_str = f"sku:{clean_sku}"
    
    # Modern GraphQL query relying on `url` and variant-level integration
    graphql_query = """
    query getVariantOrProductBySKU($query: String!) {
      productVariants(first: 1, query: $query) {
        edges {
          node {
            image {
              url
              altText
            }
            product {
              title
              images(first: 1) {
                edges {
                  node {
                    url
                    altText
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
        "X-Shopify-Access-Token": SHOPIFY_TOKEN
    }
    
    try:
        response = requests.post(
            SHOPIFY_ENDPOINT,
            headers=headers,
            json={"query": graphql_query, "variables": {"query": query_str}},
            timeout=5
        )
        response.raise_for_status()
        data = response.json()
        
        # Check for GraphQL structural errors bypassing HTTP Status Codes
        if "errors" in data:
            return {"sku": sku, "image_url": None, "alt_text": f"Product {sku}"}

        variants = data.get("data", {}).get("productVariants", {}).get("edges", [])
        
        if variants:
            node = variants[0]["node"]
            
            # 1. Try to get the variant-specific image first
            if node.get("image") and node["image"].get("url"):
                return {
                    "sku": sku,
                    "image_url": node["image"]["url"],
                    "alt_text": node["image"].get("altText") or node.get("product", {}).get("title", f"Product {sku}")
                }
                
            # 2. Fallback to the main product image
            product_images = node.get("product", {}).get("images", {}).get("edges", [])
            if product_images:
                img_node = product_images[0]["node"]
                return {
                    "sku": sku,
                    "image_url": img_node.get("url"),
                    "alt_text": img_node.get("altText") or node.get("product", {}).get("title", f"Product {sku}")
                }
                
    except Exception:
        pass
        
    return {"sku": sku, "image_url": None, "alt_text": f"Product {sku}"}

@st.cache_data(ttl=3600, show_spinner=False)
def get_shopify_images_batch(sku_list):
    """Fetch images in parallel batches safely preventing API limits"""
    if not sku_list:
        return pd.DataFrame(columns=['sku', 'image_url', 'alt_text'])
    
    results = []
    
    # Limiting max_workers to 5 to respect Shopify API Leak Rates without getting 429 Throttle blocks
    with ThreadPoolExecutor(max_workers=5) as executor: 
        future_to_sku = {executor.submit(fetch_single_product_image, sku): sku for sku in sku_list}
        
        progress_bar = st.progress(0, text="📸 Loading product images...")
        completed = 0
        
        for future in as_completed(future_to_sku):
            try:
                result = future.result(timeout=5)
                results.append(result)
            except Exception:
                sku = future_to_sku[future]
                results.append({"sku": sku, "image_url": None, "alt_text": f"Product {sku}"})
            
            completed += 1
            progress_bar.progress(completed / len(sku_list))
        
        progress_bar.empty()
    
    return pd.DataFrame(results)

@st.cache_data(ttl=300, show_spinner=False)
def fetch_inventory_data(order_start, order_end, suffix, product_start=None, product_end=None):
    """Fetch inventory data with caching"""
    query = """
    query GetInventory(
      $orderStart: DateTime
      $orderEnd: DateTime
      $productStart: DateTime
      $productEnd: DateTime
    ) {
      executesp_inventory(
        OrderStartDate: $orderStart
        OrderEndDate: $orderEnd
        ProductStartDate: $productStart
        ProductEndDate: $productEnd
      ) {
        product_id
        sku
        title
        productType
        totalInventory
        quantity
        status
      }
    }
    """
    
    try:
        headers = get_fabric_headers()
        if not headers:
            return pd.DataFrame()
        
        variables = {
            "orderStart": order_start,
            "orderEnd": order_end,
            "productStart": product_start,
            "productEnd": product_end
        }
        
        response = requests.post(
            FABRIC_ENDPOINT,
            headers=headers,
            json={"query": query, "variables": variables},
            timeout=15
        )
        response.raise_for_status()
        
        data = response.json()
        items = data.get("data", {}).get("executesp_inventory", [])
        
        if not items:
            return pd.DataFrame(columns=[
                'product_id', 'sku', 'title', 'productType', 
                'currentstock', f'qty_{suffix}', 'initial_quantity'
            ])
        
        df = pd.DataFrame(items)
        
        # Remove cancelled orders
        df = df[(df['status'].str.upper() != 'CANCELLED')]
        df['totalInventory'] = df['totalInventory'].apply(lambda x: max(x, 0))
        
        # Aggregate
        result_df = (
            df.groupby(
                ['product_id', 'sku', 'title', 'productType', 'totalInventory'],
                as_index=False
            )
            .agg(**{f'qty_{suffix}': ('quantity', 'sum')})
        )
        
        result_df = result_df.rename(columns={'totalInventory': 'currentstock'})
        result_df['initial_quantity'] = result_df['currentstock'] + result_df[f'qty_{suffix}']
        
        return result_df
        
    except Exception as e:
        st.error(f"Error fetching data: {e}")
        return pd.DataFrame()

def format_number(num):
    """Format numbers with K/M suffix"""
    if num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(num)

# =========================
# Sidebar UI
# =========================
with st.sidebar:
    st.markdown("""
        <div style="text-align: center; padding: 1rem; background: white; border-radius: 15px; margin-bottom: 1rem;">
            <h3 style="color: #667eea;">⚙️ Fast Analytics</h3>
        </div>
    """, unsafe_allow_html=True)
    
    # Quick date presets
    date_preset = st.radio(
        "📅 Quick Select",
        ["Last 7 days", "Last 14 days", "Last 30 days", "Custom"],
        horizontal=True
    )
    
    if date_preset == "Custom":
        col1, col2 = st.columns(2)
        with col1:
            product_launch_date = st.date_input(
                "Launch Date",
                value=date.today() - timedelta(days=14),
                format="DD-MM-YYYY"
            )
        with col2:
            analysis_end_date = st.date_input(
                "End Date",
                value=date.today(),
                format="DD-MM-YYYY"
            )
    else:
        days_map = {
            "Last 7 days": 7,
            "Last 14 days": 14,
            "Last 30 days": 30
        }
        days = days_map[date_preset]
        product_launch_date = date.today() - timedelta(days=days)
        analysis_end_date = date.today()
    
    st.divider()
    
    # Quick filters
    st.markdown("### 🔍 Quick Filters")
    
    show_new_only = st.checkbox("✨ New Products Only", value=False)
    min_perf = st.slider("📈 Min Performance %", 0, 100, 0, 5)
    
    # Image toggle
    show_images = st.checkbox("🖼️ Show Product Images", value=True)
    
    st.divider()
    
    # Analysis button
    run_query = st.button(
        "🚀 Run Analysis", 
        type="primary", 
        use_container_width=True
    )

# =========================
# Main Analysis
# =========================
if run_query:
    with st.spinner("🔄 Loading data..."):
        # Format dates
        launch_start = product_launch_date.strftime("%Y-%m-%d") + "T00:00:00Z"
        launch_end = product_launch_date.strftime("%Y-%m-%d") + "T23:59:59Z"
        analysis_end = analysis_end_date.strftime("%Y-%m-%d") + "T23:59:59Z"
        
        # Fetch data in parallel using st.status
        with st.status("📊 Fetching data...", expanded=True) as status:
            st.write("⏳ Loading launch products...")
            df_launch = fetch_inventory_data(
                launch_start, analysis_end, "launch",
                launch_start, launch_end
            )
            
            st.write("⏳ Loading sales data...")
            df_sales = fetch_inventory_data(
                launch_start, analysis_end, "sale"
            )
            
            status.update(label="✅ Data loaded!", state="complete")
        
        if df_launch.empty and df_sales.empty:
            st.warning("No data found for selected dates.")
            st.stop()
        
        # Process data
        common_cols = ['product_id', 'sku', 'title', 'productType']
        
        # Find existing products (with sales but not in launch)
        if not df_sales.empty and not df_launch.empty:
            df_existing = (
                df_sales.merge(
                    df_launch[common_cols],
                    on=common_cols,
                    how='left',
                    indicator=True
                )
                .query('_merge == "left_only"')
                .drop(columns=['_merge'])
            )
        else:
            df_existing = df_sales.copy() if not df_sales.empty else pd.DataFrame()
        
        # Process existing products
        if not df_existing.empty:
            df_existing_agg = (
                df_existing
                .groupby(['product_id', 'sku', 'title', 'productType'], as_index=False)
                .agg({
                    'initial_quantity': 'sum',
                    'currentstock': 'sum'
                })
            )
            df_existing_agg['total_sold'] = df_existing_agg['initial_quantity'] - df_existing_agg['currentstock']
            df_existing_agg['performance_pct'] = np.where(
                df_existing_agg['initial_quantity'] > 0,
                (df_existing_agg['total_sold'] / df_existing_agg['initial_quantity']) * 100,
                0.0
            ).round(2)
            df_existing_agg['category'] = 'Existing'
        
        # Process launch products
        if not df_launch.empty:
            df_launch_agg = df_launch.copy()
            df_launch_agg['total_sold'] = df_launch_agg['qty_launch']
            df_launch_agg['performance_pct'] = np.where(
                df_launch_agg['initial_quantity'] > 0,
                (df_launch_agg['total_sold'] / df_launch_agg['initial_quantity']) * 100,
                0.0
            ).round(2)
            df_launch_agg['category'] = 'New'
        
        # Combine
        dfs_to_concat = []
        if not df_launch.empty:
            dfs_to_concat.append(df_launch_agg[['product_id', 'sku', 'title', 'productType', 
                                                'currentstock', 'total_sold', 'performance_pct', 'category']])
        if not df_existing.empty:
            dfs_to_concat.append(df_existing_agg[['product_id', 'sku', 'title', 'productType', 
                                                 'currentstock', 'total_sold', 'performance_pct', 'category']])
        
        df_final = pd.concat(dfs_to_concat, ignore_index=True) if dfs_to_concat else pd.DataFrame()
        
        # Apply filters
        if not df_final.empty:
            df_final = df_final[df_final['performance_pct'] >= min_perf]
            if show_new_only:
                df_final = df_final[df_final['category'] == 'New']
            
            # Add performance rating
            df_final['rating'] = pd.cut(
                df_final['performance_pct'],
                bins=[0, 25, 50, 75, 100],
                labels=['Low', 'Medium', 'High', 'Excellent']
            )
            
            # Load images only if needed
            if show_images and not df_final.empty:
                sku_list = df_final['sku'].tolist()[:50]  # Limit to first 50 for speed
                df_images = get_shopify_images_batch(sku_list)
                
                # Merge on sku
                df_final['sku'] = df_final['sku'].astype(str)
                df_images['sku'] = df_images['sku'].astype(str)
                df_final = df_final.merge(df_images, on='sku', how='left')
            else:
                df_final['image_url'] = None
                df_final['alt_text'] = None
            
            st.session_state['df'] = df_final
            st.session_state['show_images'] = show_images
            st.session_state['loaded'] = True

# =========================
# Dashboard Display
# =========================
if 'df' in st.session_state and st.session_state['loaded']:
    df = st.session_state['df']
    show_images = st.session_state.get('show_images', True)
    
    # Quick Stats
    st.markdown("### 📊 Key Metrics")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        new_count = len(df[df['category']=='New']) if 'category' in df.columns else 0
        existing_count = len(df[df['category']=='Existing']) if 'category' in df.columns else 0
        
        st.markdown(f"""
            <div class="metric-card">
                <h4 style="color:#666;">Products</h4>
                <h2 style="color:#667eea;">{len(df)}</h2>
                <p>New: {new_count} | Existing: {existing_count}</p>
            </div>
        """, unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"""
            <div class="metric-card">
                <h4 style="color:#666;">Inventory</h4>
                <h2 style="color:#667eea;">{format_number(int(df['currentstock'].sum()))}</h2>
                <p>Units in stock</p>
            </div>
        """, unsafe_allow_html=True)
    
    with col3:
        st.markdown(f"""
            <div class="metric-card">
                <h4 style="color:#666;">Sold</h4>
                <h2 style="color:#667eea;">{format_number(int(df['total_sold'].sum()))}</h2>
                <p>Total units sold</p>
            </div>
        """, unsafe_allow_html=True)
    
    with col4:
        avg_perf = df['performance_pct'].mean() if not df.empty else 0
        color = "#4caf50" if avg_perf >= 50 else "#ff9800"
        st.markdown(f"""
            <div class="metric-card">
                <h4 style="color:#666;">Avg Performance</h4>
                <h2 style="color:{color};">{avg_perf:.1f}%</h2>
                <p>Sales vs inventory</p>
            </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # Category Performance
    if 'productType' in df.columns and not df['productType'].isna().all():
        st.markdown("""
            <div class="section-header">
                <h3>🏷️ Category Performance</h3>
            </div>
        """, unsafe_allow_html=True)
        
        cat_stats = df.groupby('productType').agg({
            'sku': 'count',
            'total_sold': 'sum',
            'performance_pct': 'mean'
        }).round(2).reset_index()
        cat_stats.columns = ['Category', 'Products', 'Units Sold', 'Performance %']
        cat_stats = cat_stats.sort_values('Performance %', ascending=False)
        
        st.dataframe(
            cat_stats,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Performance %": st.column_config.ProgressColumn(
                    "Performance",
                    format="%.1f%%",
                    min_value=0,
                    max_value=100
                )
            }
        )
        
        st.divider()
    
    # Product Grid
    st.markdown(f"""
        <div class="section-header">
            <h3>📦 Products</h3>
            <p style="color:#666;">Showing {min(50, len(df))}/{len(df)} products</p>
        </div>
    """, unsafe_allow_html=True)
    
    # Search and sort
    col1, col2 = st.columns([2, 1])
    with col1:
        search = st.text_input("🔍 Search products", placeholder="Product name or SKU...")
    with col2:
        sort = st.selectbox("Sort by", ["Performance", "Sold", "Name"])
    
    # Filter and sort
    df_display = df.copy()
    if search:
        df_display = df_display[
            df_display['title'].str.contains(search, case=False, na=False) |
            df_display['sku'].str.contains(search, case=False, na=False)
        ]
    
    if sort == "Performance":
        df_display = df_display.sort_values('performance_pct', ascending=False)
    elif sort == "Sold":
        df_display = df_display.sort_values('total_sold', ascending=False)
    else:
        df_display = df_display.sort_values('title')
    
    # Display in grid
    cols = st.columns(3)
    for idx, (_, row) in enumerate(df_display.head(50).iterrows()):
        with cols[idx % 3]:
            
            image_url = row.get("image_url")

            if image_url:
                try:
                    response = requests.get(image_url, timeout=5)
                    response.raise_for_status()
                    img = Image.open(BytesIO(response.content))
                    st.image(img, width=250)
                except Exception:
                    st.warning("Image failed to load")
            else:
                st.info("No Image")
            
            # Product info
            st.markdown(f"""
                <div style="padding: 10px 0;">
                    <strong>{row['title'][:40]}{'...' if len(row['title']) > 40 else ''}</strong><br>
                    <span style="color: #666; font-size: 0.9rem;">SKU: {row['sku']}</span><br>
                    <span style="color: #667eea; font-size: 1.3rem; font-weight: bold;">{row['performance_pct']:.1f}%</span>
                    <div style="display: flex; gap: 10px; margin-top: 5px;">
                        <span class="badge badge-success">Stock: {int(row['currentstock'])}</span>
                        <span class="badge badge-warning">Sold: {int(row['total_sold'])}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)
    
    # Export
    st.divider()
    csv = df.drop(columns=['image_url', 'alt_text'], errors='ignore').to_csv(index=False).encode('utf-8')
    st.download_button(
        "📥 Download Data",
        csv,
        f"products_{date.today()}.csv",
        "text/csv",
        use_container_width=True
    )

# Footer
st.markdown(f"""
    <div style="text-align: center; margin-top: 2rem; padding: 1rem; background: #f8f9fa; border-radius: 10px;">
        <p style="color: #666;">⚡ Fast Analytics | Loaded in seconds | {datetime.now().strftime("%H:%M:%S")}</p>
    </div>
""", unsafe_allow_html=True)
