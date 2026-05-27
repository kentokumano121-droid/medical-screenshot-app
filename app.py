import streamlit as st
import os
import io
import zipfile
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
    # 1. 画面の入力欄に文字が入っていればそれを最優先で使う
    if input_api_key:
        return input_api_key
        
    # 2. それ以外は環境変数やSecretsを探す（予備）
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None

# --- アプリの基本設定 ---
st.set_page_config(page_title="SnapBrief", layout="centered", page_icon="🩺")

# --- カスタムレイアウト ＆ 圧倒的モダンCSSの適用 ---
st.markdown("""
    <style>
    /* 1. 不要なメニューの非表示（サイドバーボタンを巻き添えにしないよう修正） */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* 2. 背景をApple風のクリーンな超淡いグレーに */
    .stApp {
        background-color: #F8F9FA;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    
    /* 3. ヘッダーを左上にスタイリッシュに配置（業務用感を排除） */
    .custom-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 1rem 0;
        border-bottom: 1px solid #E5E7EB;
        margin-bottom: 2rem;
    }
    .app-title {
        font-size: 1.4rem !important;
        font-weight: 800 !important;
        color: #1F2937;
        letter-spacing: -0.05em;
    }
    .app-subtitle {
        font-size: 0.85rem;
        color: #6B7280;
    }
    
    /* 4. アップロードエリアをミニマルに */
    div[data-testid="stFileUploadDropzone"] {
        background-color: #FFFFFF !important;
        border: 1px dashed #D1D5DB !important;
        border-radius: 16px !important;
        padding: 2.5rem !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.02) !important;
    }
    
    /* 5. 各種ボタンを「フラットで高品質なタブ風」デザインに */
    div.stButton > button {
        border-radius: 12px !important;
        padding: 0.6rem 1.5rem !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        transition: all 0.2s ease !important;
    }
    /* メインボタン（青） */
    div.stButton > button[kind="primary"] {
        background-color: #007AFF !important;
        border: none !important;
        color: white !important;
        box-shadow: 0 4px 12px rgba(0, 122, 255, 0.2) !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #0062CC !important;
        box-shadow: 0 6px 16px rgba(0, 122, 255, 0.3) !important;
    }
    /* 削除・セカンダリボタン（フラットグレー） */
    div.stButton > button[kind="secondary"] {
        background-color: #F3F4F6 !important;
        border: 1px solid #E5E7EB !important;
        color: #4B5563 !important;
    }
    div.stButton > button[kind="secondary"]:hover {
        background-color: #E5E7EB !important;
        color: #1F2937 !important;
    }
    
    /* 6. 人間確認フォーム（すりガラス・極薄シャドウカード） */
    div[data-testid="stForm"] {
        background-color: #FFFFFF !important;
        border: 1px solid #E5E7EB !important;
        border-radius: 20px !important;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.05) !important;
        padding: 2rem !important;
        margin-top: 2rem;
    }
    
    /* 7. キー入力開閉パネル（Expander）を馴染ませる */
    .stExpander {
        background-color: #FFFFFF !important;
        border: 1px solid #E5E7EB !important;
        border-radius: 12px !important;
        margin-bottom: 1.5rem !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.01) !important;
    }
    </style>
""", unsafe_allow_html=True)

# --- 独自ヘッダーの描画（ダサい中央タイトルを廃止） ---
st.markdown("""
    <div class="custom-header">
        <div class="app-title">🩺 SnapBrief</div>
        <div class="app-subtitle">NotebookLM スクショ自動分類・PDF結合ツール</div>
    </div>
""", unsafe_allow_html=True)

# --- 画面上部にスマートに格納されたAPIキー設定欄 ---
with st.expander("🔑 API Key 設定 (最初に一度入力してください)"):
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
# ① まずアップローダーを画面に配置する（ここで uploaded_files が定義される）
uploaded_files = st.file_uploader(
    "スクリーンショットをアップロード（複数選択可）", 
    accept_multiple_files=True, 
    type=["png", "jpg", "jpeg", "webp"],
    key=f"uploader_{st.session_state.uploader_key}" # 動的キーを適用
)

# ② アップローダーの下に一括削除ボタンを配置する
# （uploaded_files が定義された後なのでエラーになりません）
if st.session_state.results or uploaded_files:
    if st.button("🗑️ アップロード画像と結果をすべてクリア", type="secondary", use_container_width=True):
        st.session_state.results = None
        st.session_state.zip_bytes = None
        st.session_state.uploader_key += 1 # キーを増やすことでアップローダーを強制リセット
        st.rerun() # 画面をリロードして状態をリセット
        
# ==========================================
# フェーズ2: AIによるタイトル抽出と自動ルビ振り
# ==========================================
if uploaded_files:
    if st.button("AIでタイトルとルビを自動抽出", type="primary"):
        with st.spinner("Gemini APIで画像を解析中...（枚数が多いと数秒〜数十秒かかります）"):
            
            # ファイル名順（アップロード順）にソート
            uploaded_files.sort(key=lambda x: x.name)
            
            # Pillow Imageリスト作成（iOS特有のEXIF回転情報も補正）
            images = []
            for f in uploaded_files:
                img = Image.open(f)
                img = ImageOps.exif_transpose(img)
                images.append(img)
            
            api_key = get_api_key()
            if not api_key:
                st.error("APIキーが設定されていません。`.env` または Streamlitの `Secrets` に `GEMINI_API_KEY` を設定してください。")
                st.stop()
            
            client = genai.Client(api_key=api_key)
            
            prompt = """
            あなたは医学生の学習ノート整理アシスタントです。
            提供された複数のスクリーンショット画像には、NotebookLMで生成された「〇〇について解説して。」などのQ&Aが含まれています。
            各画像について主題（〇〇の部分）を抽出し、その読み仮名の先頭カタカナ1文字を付与したファイル名（例：ア_アジソン病、ハ_橋本病）を作成してください。

            重要なルール：
            1. 各画像の前には「画像インデックス: X」というテキストを付与して渡しています。JSON出力の image_index にはこのXの数値を正確に指定してください。
            2. 画像は全部で複数枚あります。0番から最後の画像まで「1枚も漏らさずに」すべての画像に対して結果を出力してください。
            3. 連続する画像が同じ主題について説明している場合（前の画像からの続きなど）、必ず「全く同じファイル名」を出力してください。これにより後で1つのPDFに結合されます。
            4. 画像内に明確な質問文がない場合（解説の続きのページなど）でも、前後の文脈や内容から最も適切な医学用語・主題を推測し、ファイル名を作成してください。
            """
            
            # 【修正ポイント】画像と名札（テキスト）を交互にリストに格納する
            contents = []
            for i, img in enumerate(images):
                contents.append(f"画像インデックス: {i}")
                contents.append(img)
            contents.append(prompt)
            
            try:
                # Gemini API (Structured Outputs) 呼び出し
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents, # 修正したリストを渡す
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ThemeList,
                        temperature=0.0, # ズレを徹底的に防ぐため、より決定論的（0.0）にする
                    )
                )
                
                # Pydanticモデルで検証・パース
                theme_list = ThemeList.model_validate_json(response.text)
                
                results = []
                for i, img in enumerate(images):
                    file_name = f"未分類_{i}"
                    # 対応するインデックスの推測ファイル名を探す
                    matched = next((t for t in theme_list.themes if t.image_index == i), None)
                    if matched:
                        file_name = matched.file_name
                    
                    results.append({
                        "image": img,
                        "file_name": file_name,
                        "original_name": uploaded_files[i].name
                    })
                
                # 状態を保存してリロード
                st.session_state.results = results
                st.session_state.zip_bytes = None 
                st.success("解析が完了しました！下で内容を確認・修正してください。")
                
            except Exception as e:
                st.error(f"エラーが発生しました: {e}")

# ==========================================
# フェーズ3: Human-in-the-Loop（確認と修正）
# ==========================================
if st.session_state.results:
    st.divider()
    st.subheader("📝 抽出結果の確認と修正")
    st.info("💡 ヒント: 同じファイル名になっている画像は、自動的に1つのPDFファイルとして結合されます。")
    
    # st.formを使うことで、入力中の不意な画面リロードを防止（iOSでのUX向上）
    with st.form("edit_form"):
        for i, item in enumerate(st.session_state.results):
            col1, col2 = st.columns([1, 2], vertical_alignment="center")
            with col1:
                st.image(item["image"], use_container_width=True)
            with col2:
                # 各画像のファイル名を入力可能なテキストボックスとして表示
                st.text_input(
                    label=f"画像 {i+1} のファイル名", 
                    value=item["file_name"], 
                    key=f"name_{i}"
                )
        
        # ==========================================
        # フェーズ4: PDF生成とZIP圧縮
        # ==========================================
        submitted = st.form_submit_button("✅ 確定してPDF化＆ZIP圧縮", type="primary")

    if submitted:
        with st.spinner("PDFを生成し、ZIPファイルに圧縮しています..."):
            # 同じファイル名（修正後）の画像をグループ化
            groups = defaultdict(list)
            for i, item in enumerate(st.session_state.results):
                updated_name = st.session_state[f"name_{i}"]
                groups[updated_name].append(item["image"])
            
            # メモリ上でZIPファイルを作成
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_name, imgs in groups.items():
                    pdf_images = []
                    # PDF化のためにRGBA等のカラーモードをRGBに統一
                    for img in imgs:
                        if img.mode != 'RGB':
                            pdf_images.append(img.convert('RGB'))
                        else:
                            pdf_images.append(img)
                    
                    if pdf_images:
                        pdf_buffer = io.BytesIO()
                        # Pillowの標準機能で1つにまとめたPDFを生成
                        pdf_images[0].save(
                            pdf_buffer, 
                            format="PDF", 
                            save_all=True, 
                            append_images=pdf_images[1:]
                        )
                        # OS互換性を高めるためのファイル名サニタイズ
                        safe_file_name = file_name.replace("/", "／").replace("\\", "＼")
                        zf.writestr(f"{safe_file_name}.pdf", pdf_buffer.getvalue())
            
            # 作成したZIPデータをセッションに保存
            st.session_state.zip_bytes = zip_buffer.getvalue()
            st.success("🎉 すべてのPDF化とZIP圧縮が完了しました！")

import base64 # ※もしファイル上部の import 群になければ追記してください

# ZIPデータが存在する場合はダウンロードボタンを表示
if st.session_state.zip_bytes:
    st.divider()
    
    # ZIPデータをBase64エンコードして、別タブで開くカスタムリンクを作成
    b64 = base64.b64encode(st.session_state.zip_bytes).decode()
    href = f'''
    <a href="data:application/zip;base64,{b64}" download="Goodnotes_Import.zip" target="_blank" 
       style="display: block; text-align: center; padding: 0.5em 1em; color: white; background-color: #FF4B4B; text-decoration: none; border-radius: 0.5rem; font-weight: bold; margin-bottom: 10px;">
       📥 ZIPファイルをダウンロード（別タブで開きます）
    </a>
    '''
    st.markdown(href, unsafe_allow_html=True)
    st.info("💡 ダウンロード画面が開いたら、保存後にそのタブを閉じることで、この画面（APIキーなどの状態）を維持したまま作業を続けられます。")
