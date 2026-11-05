# 圖片文字擷取 Agent

**由 CYX STUDIO 製作。**

這是一款以 Python、Gradio 與 Google Gemini API 建立的圖片文字擷取工具，可將圖片中的主要文字轉錄成純文字，適合處理截圖與多張圖片。

## 功能

- 支援多張圖片，依選取順序分別顯示結果與處理狀態。
- 保留原文中的符號與段落，可選擇移除行首 Markdown 格式。
- 支援直式長截圖分段處理，以及指定主要模型與備援模型。
- 可在畫面輸入 API Key，或從本機 `.env` 讀取。

## 安裝與啟動

需要 Python 3、Gemini API Key 和網路連線。在 macOS 的終端機進入專案資料夾後執行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

開啟終端機顯示的網址，通常為 `http://127.0.0.1:7860`。將 Gemini API Key 輸入畫面，或在專案資料夾建立 `.env` 檔案：

```dotenv
GEMINI_API_KEY=你的金鑰
```

也可在 `.env` 設定 `GEMINI_MODEL`，或直接在畫面更改模型。可用模型與額度依 Google 帳戶而異。完成後在終端機按 `Control + C` 停止程式，輸入 `deactivate` 離開虛擬環境。

## 使用注意事項

圖片會傳送至 Gemini API，請先確認內容適合傳送；API 使用可能產生費用。長截圖分段會增加請求次數與耗時，切割處可能截斷文字，請核對結果。文字辨識可能有誤，重要內容請與原圖比對。

更多操作細節請參考 [start.txt](start.txt)。
