import streamlit as st
import os
import io
import zipfile
import base64
from collections import defaultdict
from PIL import Image, ImageOps

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# --- Pydantic スキーマ定義 ---
class ImageTheme(BaseModel):
    image_index: int = Field(description="画像のインデックス(0始まり)")
    file_name: str = Field(description="推測したファイル名（例：ア_アジソン病、ハ_橋本病など）")

class ThemeList(BaseModel):
    themes: list[ImageTheme]

# --- ヘルパー関数 ---
def get_api_key():
    """入力欄、環境変数、またはStreamlit SecretsからAPIキーを取得"""
    if input_api_key:
        return input_api_key
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None

# --- アプリの基本設定 ---
st.set_page_config(page_title="SnapBrief", layout="centered", page_icon="🩺")

# --- iPad特化型 モダン・ダークモードCSSの適用 ---
st.markdown("""
    <style>
    /* 1. 不要なメニューの非表示 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 2. 背景を漆黒（Apple Dark Mode風）に */
    .stApp {
        background-color: #000000;
        color: #E5E5EA;
        font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    }
    
    /* 3. 洗練されたヘッダー */
    .custom-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 1.5rem 0;
        border-bottom: 1px solid #2C2C2E;
        margin-bottom: 2.5rem;
    }
    .app-title {
        font-size: 1.6rem !important;
        font-weight: 800 !important;
        color: #FFFFFF;
        letter-spacing: -0.03em;
    }
    .app-subtitle {
        font-size: 0.9rem;
        color: #8E8E93;
    }
    
    /* 4. アップロードエリアをダーク＆ミニマルに */
    div[data-testid="stFileUploadDropzone"] {
        background-color: #1C1C1E !important;
        border: 2px dashed #3A3A3C !important;
        border-radius: 20px !important;
        padding: 3.5rem 2rem !important;
    }
    div[data-testid="stFileUploadDropzone"] * {
        color: #E5E5EA !important;
    }
    
    /* 5. iPadでのタップに最適化された巨大ボタン */
    div.stButton > button {
        border-radius: 16px !important;
        padding: 0.8rem 1.5rem !important;
        font-weight: 600 !important;
        font-size: 1.05rem !important;
        min-height: 54px !important; /* タップ領域の確保 */
        transition: all 0.2s ease !important;
    }
    /* メインボタン（ディープネイビー） */
    div.stButton > button[kind="primary"] {
        background-color: #0A5CFF !important;
        border: none !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 14px rgba(10, 92, 255, 0.3) !important;
    }
    div.stButton > button[kind="primary"]:active {
        transform: scale(0.98);
    }
    /* クリア・削除ボタン（ダークブラウン/ウォームグレー系） */
    div.stButton > button[kind="secondary"] {
        background-color: #2A2421 !important;
        border: 1px solid #4A3C31 !important;
        color: #D4C4B7 !important;
    }
    div.stButton > button[kind="secondary"]:active {
        transform: scale(0.98);
    }
    
    /* 6. フォームとExpander（カードUI） */
    div[data-testid="stForm"], .stExpander {
        background-color: #1C1C1E !important;
        border: 1px solid #2C2C2E !important;
        border-radius: 18px !important;
    }
    
    /* 7. テキスト入力欄のダーク化 */
    .stTextInput > div > div > input {
        background-color: #2C2C2E !important;
        color: #FFFFFF !important;
        border: 1px solid #3A3A3C !important;
        border-radius: 12px !important;
        padding: 0.7rem !important;
    }
    
    /* 8. テキストの視認性確保 */
    h1, h2, h3, h4, p, label {
        color: #E5E5EA !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 独自ヘッダーの描画 ---
st.markdown("""
    <div class="custom-header">
        <div class="app-title">SnapBrief</div>
        <div class="app-subtitle">Notes to PDF & ZIP</div>
    </div>
""", unsafe_allow_html=True)

# --- 画面上部にスマートに格納されたAPIキー設定欄 ---
with st.expander("API Key 設定 (初回のみ)"):
    input_api_key = st.text_input(
        "Gemini APIキー", 
        type="password", 
        placeholder="AIzaSy...",
        help="Google AI Studioで取得したキーを入力してください。"
    )

# --- セッションステートの初期化 ---
if "results" not in st.session_state:
    st.session_state.results = None
if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# ==========================================
# フェーズ1: 画像アップロード
# ==========================================
uploaded_files = st.file_uploader(
    "スクリーンショットをアップロード（複数選択可）", 
    accept_multiple_files=True, 
    type=["png", "jpg", "jpeg", "webp"],
    key=f"uploader_{st.session_state.uploader_key}"
)

if st.session_state.results or uploaded_files:
    if st.button("アップロード画像と結果をクリア", type="secondary", use_container_width=True):
        st.session_state.results = None
        st.session_state.zip_bytes = None
        st.session_state.uploader_key += 1 
        st.rerun()
        
# ==========================================
# フェーズ2: AIによるタイトル抽出と自動ルビ振り
# ==========================================
if uploaded_files:
    if st.button("AIでタイトルとルビを自動抽出", type="primary", use_container_width=True):
        with st.status("AIで画像を解析中...", expanded=True) as status:
            
            st.write("画像を読み込んでいます...")
            uploaded_files.sort(key=lambda x: x.name)
            
            original_images = []
            api_images = []
            
            for f in uploaded_files:
                img = Image.open(f)
                img = ImageOps.exif_transpose(img)
                original_images.append(img) 
                
                img_api = img.copy()
                img_api.thumbnail((1024, 1024)) 
                api_images.append(img_api)
            
            api_key = get_api_key()
            if not api_key:
                st.error("APIキーが設定されていません。")
                st.stop()
            
            client = genai.Client(api_key=api_key)
            
            prompt = """
            あなたは医学生の学習ノート整理アシスタントです。
            提供された複数のスクリーンショット画像には、NotebookLMで生成された「〇〇について解説して。」などのQ&Aが含まれています。
            各画像について主題（〇〇の部分）を抽出し、その読み仮名の先頭カタカナ1文字を付与したファイル名を作成してください。

            重要なルール：
            1. 「〇〇」の部分は一切省略したり、文節で短く区切ったりせず、主題全体を完全に抽出してください。
               (例) 画像に「急性心筋梗塞の治療フローについて解説して」とある場合、「キ_急性心筋梗塞」ではなく「キ_急性心筋梗塞の治療フロー」とする。
            2. 各画像の前には「画像インデックス: X」というテキストを付与して渡しています。JSON出力の image_index にはこのXの数値を正確に指定してください。
            3. 画像は全部で複数枚あります。0番から最後の画像まで「1枚も漏らさずに」すべての画像に対して結果を出力してください。
            4. 連続する画像が同じ主題について説明している場合（前の画像からの続きなど）、必ず「全く同じファイル名」を出力してください。これにより後で1つのPDFに結合されます。
            5. 画像内に明確な質問文がない場合でも、前後の文脈や内容から最も適切な医学用語・主題を推測し、ファイル名を作成してください。
            """
            
            contents = []
            for i, img_api in enumerate(api_images):
                contents.append(f"画像インデックス: {i}")
                contents.append(img_api)
            contents.append(prompt)
            
            try:
                st.write("☁️ Geminiにデータを送信・解析中です...")
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ThemeList,
                        temperature=0.0,
                    )
                )
                
                theme_list = ThemeList.model_validate_json(response.text)
                
                results = []
                for i, img_orig in enumerate(original_images):
                    file_name = f"未分類_{i}"
                    matched = next((t for t in theme_list.themes if t.image_index == i), None)
                    if matched:
                        file_name = matched.file_name
                    
                    results.append({
                        "image": img_orig,
                        "file_name": file_name,
                        "original_name": uploaded_files[i].name
                    })
                
                st.session_state.results = results
                st.session_state.zip_bytes = None 
                
                status.update(label="解析が完了しました！", state="complete", expanded=False)
                
            except Exception as e:
                status.update(label="エラーが発生しました", state="error", expanded=True)
                st.error(f"詳細なエラー内容: {e}")
                
# ==========================================
# フェーズ3: Human-in-the-Loop（グループごとの確認と修正）
# ==========================================
if st.session_state.results:
    st.divider()
    st.subheader("抽出結果の確認と修正")
    
    with st.form("edit_form"):
        groups = defaultdict(list)
        for item in st.session_state.results:
            groups[item["file_name"]].append(item["image"])
        
        group_keys = list(groups.keys())
        for i, ai_file_name in enumerate(group_keys):
            images = groups[ai_file_name]
            
            st.markdown(f"#### 📦 {i+1}. {ai_file_name} ({len(images)}枚)")
            
            cols_per_row = 4
            for row_start in range(0, len(images), cols_per_row):
                cols = st.columns(cols_per_row)
                for col_idx in range(cols_per_row):
                    img_idx = row_start + col_idx
                    if img_idx < len(images):
                        with cols[col_idx]:
                            st.image(images[img_idx], use_container_width=True)
            
            st.text_input(
                label="ファイル名を修正", 
                value=ai_file_name, 
                key=f"group_name_{i}",
                label_visibility="collapsed"
            )
            st.markdown("<br>", unsafe_allow_html=True)
        
        # ==========================================
        # フェーズ4: PDF生成とZIP圧縮
        # ==========================================
        st.markdown("<br>", unsafe_allow_html=True)
        submitted = st.form_submit_button("✅ 確定してPDF化＆ZIP圧縮", type="primary", use_container_width=True)

    if submitted:
        with st.spinner("PDFを生成し、ZIPファイルに圧縮しています..."):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                
                for i, ai_file_name in enumerate(group_keys):
                    final_name = st.session_state[f"group_name_{i}"]
                    imgs = groups[ai_file_name]
                    
                    pdf_images = []
                    for img in imgs:
                        if img.mode != 'RGB':
                            pdf_images.append(img.convert('RGB'))
                        else:
                            pdf_images.append(img)
                    
                    if pdf_images:
                        pdf_buffer = io.BytesIO()
                        pdf_images[0].save(
                            pdf_buffer, 
                            format="PDF", 
                            save_all=True, 
                            append_images=pdf_images[1:]
                        )
                        safe_file_name = final_name.replace("/", "／").replace("\\", "＼")
                        zf.writestr(f"{safe_file_name}.pdf", pdf_buffer.getvalue())
            
            st.session_state.zip_bytes = zip_buffer.getvalue()
            st.success("🎉 ZIP圧縮が完了しました！下のボタンからダウンロードしてください。")

# ZIPデータが存在する場合はダウンロードボタンを表示
if st.session_state.zip_bytes:
    st.divider()
    
    b64 = base64.b64encode(st.session_state.zip_bytes).decode()
    # ダウンロードボタンもダークモードに合わせたスタイリッシュなブルーに
    href = f'''
    <a href="data:application/zip;base64,{b64}" download="Goodnotes_Import.zip" target="_blank" 
       style="display: block; text-align: center; padding: 1em; color: white; background-color: #0A5CFF; text-decoration: none; border-radius: 16px; font-size: 1.1rem; font-weight: 600; margin-bottom: 10px; box-shadow: 0 6px 16px rgba(10, 92, 255, 0.3); transition: all 0.2s ease;">
       📥 ZIPファイルをダウンロード
    </a>
    '''
    st.markdown(href, unsafe_allow_html=True)
