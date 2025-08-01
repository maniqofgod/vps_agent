# Rencana Fitur / Laporan Bug

---

## Judul Tugas
Menambahkan Tombol "Test Koneksi" di Halaman Admin VPS

---

## Deskripsi
Saat ini, setelah admin menambahkan VPS worker baru, tidak ada cara mudah untuk memverifikasi apakah server utama bisa berkomunikasi dengan agen VPS tersebut. Hal ini bisa menyebabkan kebingungan jika ada masalah jaringan atau kesalahan pengetikan IP/API Key.

Tugas ini adalah untuk menambahkan tombol "Test" di samping setiap VPS worker yang terdaftar di modal "Manage VPS Workers". Ketika tombol ini diklik, backend akan mencoba menghubungi endpoint `/health` pada agen VPS yang bersangkutan dan menampilkan hasilnya (sukses atau gagal) kepada admin.

---

## File yang Relevan
*   `frontend/client/src/components/modals/AdminVPSModal.js`: Untuk menambahkan tombol "Test" di UI dan menampilkan hasilnya.
*   `frontend/client/src/services/api.js`: Untuk menambahkan fungsi `testVpsConnection(vpsId)`.
*   `backend/app/api/vps.py`: Untuk membuat endpoint baru `POST /vps/{vps_id}/test` yang akan menangani logika pengujian koneksi.
*   `vps_agent/main.py`: Endpoint `/health` di file ini akan menjadi target dari tes koneksi.

---

## Kriteria Keberhasilan
1.  Sebuah tombol "Test" muncul di sebelah tombol "Delete" untuk setiap item di daftar "Assigned VPS Workers".
2.  Ketika tombol "Test" diklik, sebuah indikator loading atau pesan "Testing..." muncul.
3.  Setelah beberapa saat, pesan tersebut berubah menjadi notifikasi yang jelas, misalnya:
    - **Sukses:** "Connection successful: Agent is online."
    - **Gagal:** "Connection failed: Could not reach agent. (Detail error...)"
4.  Log di terminal agen VPS menunjukkan adanya permintaan masuk ke endpoint `/health`.

---

## Catatan Tambahan (Opsional)
- Endpoint `/health` di `vps_agent` sudah ada, jadi tidak perlu ada perubahan di sisi agen. Fokus utama ada di frontend dan backend server utama.
- Pastikan penanganan error jelas, misalnya jika terjadi timeout atau jika agen mengembalikan status error.
