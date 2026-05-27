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
    """環境変数またはStreamlit SecretsからAPIキーを取得"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        return api_key
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None

# --- アプリの基本設定 ---
st.set_page_config(page_title="スクショ自動PDF化アプリ", layout="centered", page_icon="🩺")

st.title("🩺 学習用スクショ自動PDF化＆振り分け")
st.markdown("NotebookLMで作成したQ&Aスクショを読み込み、Geminiで自動分類してPDF化します。")

# --- セッションステートの初期化 ---
if "results" not in st.session_state:
    st.session_state.results = None
if "zip_bytes" not in st.session_state:
    st.session_state.zip_bytes = None

# ==========================================
# フェーズ1: 画像アップロード
# ==========================================
uploaded_files = st.file_uploader(
    "スクリーンショットをアップロード（複数選択可）", 
    accept_multiple_files=True, 
    type=["png", "jpg", "jpeg", "webp"]
)

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
            1. 連続する画像が同じ主題について説明している場合（前の画像からの続きなど）、必ず「全く同じファイル名」を出力してください。これにより後で1つのPDFに結合されます。
            2. 画像内に明確な質問文がない場合でも、内容から最も適切な医学用語・主題を推測し、ファイル名を作成してください。
            3. 出力は指定されたJSONスキーマに従ってください。
            """
            
            try:
                # Gemini API (Structured Outputs) 呼び出し
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=images + [prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ThemeList,
                        temperature=0.1, # 安定した抽出のため低めに設定
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

# ZIPデータが存在する場合はダウンロードボタンを表示
if st.session_state.zip_bytes:
    st.download_button(
        label="📥 ZIPファイルをダウンロードして「ファイル」に保存",
        data=st.session_state.zip_bytes,
        file_name="Goodnotes_Import.zip",
        mime="application/zip",
        type="primary",
        use_container_width=True
    )