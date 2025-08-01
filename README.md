# StreamCurl VPS Agent

Agen ringan yang dirancang untuk menerima dan menjalankan tugas streaming FFmpeg dari server utama StreamCurl. Agen ini memungkinkan Anda untuk mendistribusikan beban kerja streaming ke beberapa server (VPS), membuat aplikasi utama Anda lebih ringan dan skalabel.

## Fitur Utama

- **Instalasi Satu Perintah:** Siapkan dan jalankan agen di VPS baru hanya dengan satu baris perintah.
- **Manajemen Layanan:** Dijalankan sebagai layanan latar belakang yang persisten menggunakan **PM2**, memastikan agen otomatis berjalan kembali setelah server di-reboot.
- **Pembuatan API Key Otomatis:** Kunci API yang aman dan unik dibuat secara otomatis saat instalasi, menghilangkan kebutuhan konfigurasi manual yang rumit.
- **Skrip Kontrol Sederhana:** Dilengkapi dengan skrip `agentctl.sh` untuk mengelola layanan dengan mudah (stop, restart, lihat log, dll.).

---

## Instalasi

Untuk menginstal agen di server VPS yang bersih (direkomendasikan Ubuntu 22.04), cukup jalankan perintah berikut di terminal VPS Anda:

```bash
curl -sL https://raw.githubusercontent.com/maniqofgod/vps_agent/main/install.sh | bash
```

Skrip ini akan menangani semuanya secara otomatis:
1.  Menginstal semua dependensi sistem yang diperlukan (git, python, nodejs, pm2).
2.  Mengkloning repositori ini.
3.  Menginstal dependensi Python.
4.  Membuat API Key unik.
5.  Memulai agen sebagai layanan latar belakang menggunakan PM2.

Setelah instalasi selesai, Anda akan melihat **Kunci API** Anda ditampilkan di terminal.

### Menemukan Kunci API Anda

Salin Kunci API yang ditampilkan di akhir proses instalasi. Anda perlu memasukkan kunci ini ke panel admin server utama StreamCurl saat menambahkan VPS ini sebagai worker.

Jika Anda perlu melihat Kunci API lagi nanti, navigasikan ke direktori `vps_agent` dan jalankan:
```bash
./agentctl.sh apikey
```

---

## Manajemen Layanan

Semua manajemen layanan dilakukan melalui skrip `agentctl.sh` dari dalam direktori `vps_agent`.

```bash
cd vps_agent
```

#### Melihat Log Realtime
Untuk memantau output dari agen, termasuk stream yang sedang berjalan atau pesan error.
```bash
./agentctl.sh logs
```

#### Menghentikan Layanan
Untuk menghentikan layanan agen sepenuhnya.
```bash
./agentctl.sh stop
```

#### Memulai Ulang Layanan
Cara cepat untuk menghentikan dan memulai kembali layanan agen.
```bash
./agentctl.sh restart
```

#### Memeriksa Status Layanan
Untuk melihat status semua layanan yang dikelola oleh PM2, termasuk `vps-agent`.
```bash
./agentctl.sh status