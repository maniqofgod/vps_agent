#!/bin/bash

# Skrip kontrol untuk mengelola layanan StreamCurl VPS Agent menggunakan pm2

# Nama layanan di pm2
SERVICE_NAME="vps-agent"

# Fungsi untuk memeriksa apakah pm2 sudah terinstal
check_pm2() {
    if ! command -v pm2 &> /dev/null
    then
        echo "Error: pm2 tidak ditemukan. Silakan jalankan kembali skrip install.sh."
        exit 1
    fi
}

# Fungsi untuk menampilkan bantuan
show_help() {
    echo "Penggunaan: ./agentctl.sh [perintah]"
    echo ""
    echo "Perintah yang tersedia:"
    echo "  start     Menjalankan atau memulai ulang layanan agen"
    echo "  stop      Menghentikan layanan agen"
    echo "  restart   Memulai ulang layanan agen"
    echo "  logs      Menampilkan log realtime dari layanan agen"
    echo "  status    Menampilkan status layanan agen"
    echo "  apikey    Menampilkan Kunci API yang tersimpan"
    echo "  help      Menampilkan pesan bantuan ini"
}

# Pastikan pm2 ada
check_pm2

# Logika utama untuk menangani perintah
case "$1" in
    start)
        echo "Memastikan layanan $SERVICE_NAME berjalan..."
        # Coba restart dulu, jika gagal (karena belum ada), baru start
        # Cari path python dari venv
VENV_PYTHON="venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment tidak ditemukan. Jalankan kembali install.sh."
    exit 1
fi
# Gunakan path lengkap ke uvicorn di dalam venv
UVICORN_PATH="venv/bin/uvicorn"
pm2 restart "$SERVICE_NAME" || pm2 start "$UVICORN_PATH main:app --host 0.0.0.0 --port 8002" --name "$SERVICE_NAME" --interpreter "$VENV_PYTHON"
        pm2 save
        ;;
    stop)
        echo "Menghentikan layanan $SERVICE_NAME..."
        pm2 stop "$SERVICE_NAME"
        pm2 save
        ;;
    restart)
        echo "Memulai ulang layanan $SERVICE_NAME..."
        pm2 restart "$SERVICE_NAME"
        ;;
    logs)
        echo "Menampilkan log untuk $SERVICE_NAME... (Tekan Ctrl+C untuk keluar)"
        pm2 logs "$SERVICE_NAME"
        ;;
    status)
        pm2 list
        ;;
    apikey)
        if [ -f ".env" ]; then
            API_KEY=$(grep AGENT_API_KEY .env | cut -d '=' -f2)
            echo "========================================================================"
            echo "                 >>> KUNCI API AGEN VPS ANDA <<<"
            echo "========================================================================"
            echo ""
            echo " $API_KEY"
            echo ""
            echo "========================================================================"
        else
            echo "File .env tidak ditemukan. Jalankan instalasi terlebih dahulu."
        fi
        ;;
    help|*)
        show_help
        ;;
esac