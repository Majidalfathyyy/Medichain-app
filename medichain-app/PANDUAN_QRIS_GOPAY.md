# Panduan QRIS GoPay dan verifikasi pembayaran MediChain

## Alur pembayaran manual

Pasien membayar lewat QRIS statis GoPay Merchant, lalu mengunggah foto bukti pembayaran pada popup tagihan. Setelah pasien menekan **Kirim bukti & konfirmasi**, bukti tercatat dengan status **Menunggu verifikasi**. Tagihan tetap belum lunas sampai admin memeriksa transaksi di aplikasi GoPay Merchant dan menyetujui bukti.

Gambar yang diunggah adalah bukti untuk diperiksa, bukan konfirmasi transaksi dari GoPay. MediChain tidak menerima notifikasi otomatis dari QRIS statis. Jangan menyetujui pembayaran hanya berdasarkan gambar; pastikan transaksi benar-benar tercatat di riwayat merchant.

## Memasang gambar QRIS GoPay Merchant

1. Buka aplikasi GoPay Merchant dan pastikan toko yang dipilih benar.
2. Buka menu **Kode QR**, lalu unduh atau simpan gambar QRIS statis merchant. QRIS statis meminta pembeli memasukkan nominal sendiri. [Panduan GoPay menampilkan QRIS](https://gopay.co.id/bantuan-merchant/qris-merchant/cara-menampilkan-qris), [panduan QRIS di aplikasi](https://gopay.co.id/bantuan-merchant/pembayaran-qris/cara-menampilkan-kode-qris-di-aplikasi).
3. Simpan gambar dengan nama `gopay-qris.png` di folder `public` proyek:

   ```text
   medichain-app/public/gopay-qris.png
   ```

4. Muat ulang halaman MediChain. Jika gambar tidak ditemukan, dialog pembayaran menunjukkan petunjuk pemasangan.
5. Pindai QR dengan ponsel lain dan pastikan nama merchant yang tampil sesuai.

## Langkah pasien

1. Buka **Tagihan**, lalu tekan **Bayar** atau **Unggah ulang**.
2. Pindai QRIS dengan GoPay atau aplikasi bank/e-wallet yang mendukung QRIS.
3. Masukkan nominal yang sama persis dengan tagihan, periksa nama merchant, lalu selesaikan pembayaran.
4. Kembali ke MediChain, pilih foto bukti pembayaran berformat JPG, PNG, atau WebP (maksimal 2 MB), lalu tekan **Kirim bukti & konfirmasi**.
5. Status berubah menjadi **Menunggu verifikasi**. Jika admin menolak bukti, alasan penolakan muncul di tagihan; pasien dapat mengunggah bukti baru.

## Langkah admin

1. Buka aplikasi GoPay Merchant dan periksa riwayat transaksi toko yang benar.
2. Di MediChain, buka **Tagihan** lalu pilih **Verifikasi bukti** pada tagihan yang menunggu.
3. Cocokkan pasien/tagihan, nominal, waktu, dan transaksi berhasil di GoPay Merchant.
4. Pilih **Setujui & tandai lunas** jika transaksi cocok. Pilih **Tolak bukti** dan isi alasan jika transaksi tidak cocok atau bukti belum memadai.

Hanya admin yang dapat membuka gambar bukti dan meninjau pembayaran. Auditor dapat membaca status tagihan, tetapi tidak dapat menyetujui atau menolak bukti. Status lunas tidak dapat diatur lewat form edit tagihan atau oleh pasien.

## Migrasi database

Fitur ini menyimpan gambar bukti dan riwayat keputusan admin pada tabel `invoice_payment_proofs`. Sebelum memperbarui database yang sudah berisi data, buat dan verifikasi backup. Jalankan dari folder proyek menggunakan lingkungan Python aplikasi:

```bash
alembic upgrade head
```

Jangan jalankan alur pembayaran di deployment produksi sebelum migrasi selesai.

## Batasan QRIS statis

QRIS statis tidak membawa ID tagihan MediChain dan tidak mengirim status pembayaran ke aplikasi. Pasien memasukkan nominal secara manual; admin tetap harus memeriksa transaksi di GoPay Merchant. Tidak ada payment gateway atau webhook pada alur ini.
