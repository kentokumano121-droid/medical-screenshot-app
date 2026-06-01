from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import time

def keep_alive():
    # ご自身のStreamlitアプリのURLに書き換えてください
    url = "https://medical-screenshot-app-qejdpyjhy3e8nmxxkph7m6.streamlit.app/"
    
    options = Options()
    options.add_argument('--headless') # 画面を表示しない設定
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    print(f"アクセスを開始します: {url}")
    driver = webdriver.Chrome(options=options)
    
    # タイムアウトの設定
    driver.implicitly_wait(120)
    
    try:
        driver.get(url)
        time.sleep(10) # 完全に読み込まれるまで10秒待機
        print("正常にアクセスし、スリープを防止しました！")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    keep_alive()
