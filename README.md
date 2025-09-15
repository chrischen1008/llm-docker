# LLM + vLLM + Streamlit 部署教學

本文件說明如何安裝 Docker Desktop、設定 vLLM 及 HuggingFace 模型、並透過
Streamlit 建立前端服務。

------------------------------------------------------------------------

## 1. 安裝 Docker Desktop

1.  下載並安裝 [Docker
    Desktop](https://www.docker.com/products/docker-desktop/)\
2.  安裝時 **記得勾選啟用 WSL 2 支援**\
3.  安裝完成後，請**開啟 Docker Desktop**，以確保 Docker 服務啟動

------------------------------------------------------------------------

## 2. 變更 Docker 虛擬磁碟 (.vhdx) 位置

避免 `.vhdx` 檔案佔用 C 槽空間，可移至其他磁碟：

1.  第一次運行 Docker Desktop\

2.  右鍵任務欄的 Docker 圖示 → 進入 **Settings**\

3.  設定新的目錄，例如：

        D:\ProgramData\DockerDesktop\vm-data\DockerDesktop

4.  關閉 Docker Desktop\

5.  從默認位置複製檔案：

        C:\ProgramData\DockerDesktop\vm-data\DockerDesktop.vhdx

    到新的目錄\

6.  重新運行 Docker Desktop

------------------------------------------------------------------------

## 3. 下載 HuggingFace 模型

1.  進入虛擬環境\

2.  切換至 LLM 專案資料夾：

    ``` bash
    cd llm程式資料夾
    ```

3.  登入 HuggingFace：

    ``` bash
    huggingface-cli login
    ```

    登入 Token 需至 [HuggingFace Tokens
    設定頁面](https://huggingface.co/settings/tokens) 申請，例如：

        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

4.  下載模型：

    ``` bash
    huggingface-cli download Qwen/Qwen3-1.7B      --local-dir ./vllm_models/Qwen3-1.7B      --local-dir-use-symlinks False
    ```

    執行後，模型檔案會出現在 `./vllm_models/Qwen3-1.7B`\
    可以將檔案移動到外層的 `models/` 資料夾，或修改 `docker-compose.yml`
    以指定新路徑

------------------------------------------------------------------------

## 4. 建立 `docker-compose.yml`

在 `models` 資料夾內建立 `docker-compose.yml`：

``` yaml
version: "3.9"

services:
  vllm-service:
    image: vllm/vllm-openai:latest
    container_name: my_vllm_container
    ports:
      - "8000:8000"
    volumes:
      - ./models:/models
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - VLLM_LOGGING_LEVEL=INFO
      - HF_HUB_OFFLINE=1
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: ["gpu"]
    command:
      [
        "--model", "/models/Qwen3-0.6B",
        "--served-model-name", "Qwen3-0.6B",
        "--gpu-memory-utilization", "0.75",  # 依 GPU VRAM 大小調整
        "--max-model-len", "8000",           # 依 GPU VRAM 大小調整
        "--max-num-seqs", "16",              # 限制並行序列數量
        "--api-server-count", "1",
        "--port", "8000"
      ]

  streamlit-app:
    build: .
    container_name: my_streamlit_app
    ports:
      - "8501:8501"
    volumes:
      - .:/app
    environment:
      - VLLM_ENDPOINT=http://vllm-service:8000/v1
      - LLM_MODEL=Qwen3-0.6B
    depends_on:
      - vllm-service
```

------------------------------------------------------------------------

## 5. 啟動服務

``` bash
docker compose up -d
```

> 第一次啟動需要等待模型載入，請確認 `vllm-service` container 的 LOG
> 顯示以下訊息後再使用：

    (APIServer pid=1) INFO: Started server process [1]
    (APIServer pid=1) INFO: Waiting for application startup.
    (APIServer pid=1) INFO: Application startup complete.

------------------------------------------------------------------------

## 6. 更新容器

若有程式碼或 `docker-compose.yml` 更新，請重新建置：

``` bash
docker compose up -d --build
```

只更新特定服務，例如 `streamlit-app`：

``` bash
docker compose up -d --build streamlit-app
```

> **注意**：模型容器 (`vllm-service`)
> 不需每次更新，否則重新啟動時需重新讀取模型，啟動時間較長。

------------------------------------------------------------------------

## 7. 開始使用

當服務啟動完成後，即可透過瀏覽器進入：

    http://localhost:8501

進行互動測試。

------------------------------------------------------------------------

## 備註

-   `--gpu-memory-utilization`、`--max-model-len` 可依 GPU VRAM
    大小調整\
-   如果模型放在不同路徑，記得修改 `docker-compose.yml` 中的
    `/models/Qwen3-0.6B` 路徑\
-   `HF_HUB_OFFLINE=1` 表示容器啟動後不會再嘗試連線下載模型
