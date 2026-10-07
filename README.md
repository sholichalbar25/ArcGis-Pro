=====================================================================
CONTOUR TOOLS PRO - KONTUR 1 KLIK UNTUK ARCGIS PRO
Created by SHOLICH ALBAR
=====================================================================

Python Toolbox untuk ArcGIS Pro yang membuat kontur dari DEM dalam satu
langkah: potong DEM dengan boundary, buat kontur, haluskan, hapus kontur
noise, lalu tambahkan layer berlabel ke peta. Semua langkah memakai
setelan bawaan ArcGIS.


---------------------------------------------------------------------
1. ISI FOLDER
---------------------------------------------------------------------

  ContourToolsPro.pyt     Toolbox (file utama)
  ContourStyle.lyrx       Template simbol dan label kontur (opsional)
  README_ContourToolsPro.txt   Panduan ini

Simpan .pyt dan .lyrx di folder yang sama. Template dicari otomatis di
folder tempat .pyt berada.


---------------------------------------------------------------------
2. KEBUTUHAN
---------------------------------------------------------------------

  - ArcGIS Pro 2.x atau 3.x (Python 3)
  - Extension Spatial Analyst
  - Smooth Line (Cartography) memerlukan tingkat lisensi tertentu.
    Jika tidak tersedia, kontur tetap disimpan tanpa smoothing dan
    tool memberi peringatan.


---------------------------------------------------------------------
3. CARA PASANG
---------------------------------------------------------------------

  1. Buka panel Catalog di ArcGIS Pro.
  2. Klik kanan Toolboxes > Add Toolbox.
  3. Pilih ContourToolsPro.pyt.
  4. Buka toolbox "Contour Tools", lalu jalankan tool
     "Kontur 1 Klik".

Setelah file .pyt diubah, klik kanan toolbox > Refresh, lalu buka
ulang tool-nya.


---------------------------------------------------------------------
4. ALUR PROSES
---------------------------------------------------------------------

  [1/5] Potong DEM       Extract by Mask dengan boundary (jika ada)
  [2/5] Buat kontur      Spatial Analyst > Contour
  [3/5] Haluskan         Cartography > Smooth Line (PAEK)
  [4/5] Hapus noise      Hapus baris atribut dengan Shape_Length
                         lebih kecil dari batas (meter)
  [5/5] Index + label    Kontur index ditandai (field IdxKontur), layer
                         ditambahkan ke peta aktif: kontur index tebal
                         dan berlabel elevasi, kontur biasa tipis

Urutan 3 dan 4 sengaja begitu: nilai Shape_Length yang dipakai untuk
menghapus noise sama dengan yang Anda lihat di tabel atribut hasil
akhir.


---------------------------------------------------------------------
5. PARAMETER
---------------------------------------------------------------------

INPUT
  Input DEM (pilih dari layer di peta)
      Dropdown berisi semua layer raster di peta aktif. Saat tool
      dibuka, layer raster pertama yang terlihat terpilih otomatis.

  atau Input DEM dari file
      Untuk DEM yang belum ada di peta (tombol browse). Jika terisi,
      isian ini yang dipakai, bukan dropdown.

  Sistem koordinat DEM
      Aktif hanya jika DEM belum punya CRS. CRS dipasang ke hasil
      kontur saja; DEM asli tidak diubah.

  Input boundary (pilih dari layer di peta)
      Dropdown berisi layer poligon dan garis di peta aktif. Default:
      "(tanpa boundary)" = seluruh DEM dipakai. Jika layer punya fitur
      yang sedang diseleksi, hanya fitur terseleksi yang dipakai.

  atau Input boundary dari file
      Poligon atau garis tertutup. Jika terisi, isian ini yang dipakai.

  Sistem koordinat boundary
      Aktif hanya jika boundary belum punya CRS. Jika dikosongkan,
      dianggap sama dengan CRS DEM. Dipasang ke salinan sementara saja.

OUTPUT
  Output kontur
      Feature class hasil. Nama otomatis: <nama DEM>_Kontur di
      geodatabase proyek. Dapat diubah.

OPSI KONTUR
  Contour interval (satuan Z)      Default 0.5
  Base contour                     Default 0
  Z factor                         Default 1 (0.3048 untuk feet ke meter)
  Hapus kontur dengan Shape_Length lebih kecil dari (meter)
                                   Default 20; 0 = lewati
  Hapus hanya loop tertutup        Default tidak dicentang
  Smoothing tolerance              Default 3 Meters; kosong = tanpa
                                   smoothing

LABEL
  Kontur index tiap (satuan Z)     Default 5; 0 = tanpa index. Sebaiknya
                                   kelipatan Contour interval (mis.
                                   interval 0.5 -> index tiap 5 = setiap
                                   kontur ke-10). Kontur dengan
                                   (elevasi - base) kelipatan nilai ini
                                   menjadi index. Hanya kontur index
                                   yang dilabeli. Jika 0, semua kontur
                                   satu simbol dan semua dilabeli.
  Tambahkan ke peta dan label      Default dicentang
  Template gaya (.lyrx)            Default ContourStyle.lyrx jika ada


---------------------------------------------------------------------
6. CATATAN PENTING
---------------------------------------------------------------------

Satuan
  Semua jarak (panjang minimum noise, toleransi) dalam METER. Jika CRS
  DEM bukan meter (misalnya feet), nilai meter dikonversi otomatis dan
  tool memberi peringatan. Interval kontur dan base memakai satuan Z.

Hapus noise
  Tool membaca field Shape_Length (Shape_Leng di shapefile) dari tabel
  atribut kontur hasil, lalu menghapus baris yang nilainya di bawah
  batas. Kolom Shape_Length sendiri tidak bisa dihapus karena kolom
  sistem; yang dihapus adalah baris kontur pendeknya.

  Jika "Hapus hanya loop tertutup" dicentang, hanya loop tertutup yang
  dihapus dan garis pendek terbuka di tepi DEM dipertahankan.

CRS geografis
  Jika DEM memakai CRS geografis (derajat), panjang kontur dihitung
  geodesik dalam meter dan muncul peringatan. CRS proyeksi (misalnya
  UTM) lebih disarankan.

Overwrite
  Tool mengikuti pengaturan Overwrite ArcGIS Pro Anda. Jika output
  sudah ada dan Overwrite mati, tool berhenti dengan pesan jelas dan
  tidak menimpa file.

Daftar layer
  Daftar layer peta dibaca sekali saat dialog dibuka. Jika Anda
  menambah layer ke peta saat dialog masih terbuka, tutup dan buka
  lagi tool-nya agar layer itu muncul. Tanpa peta aktif, dropdown
  kosong; gunakan isian "dari file".

Batasan
  - DEM harus satu band (bukan citra multiband atau RGB).
  - Jika interval terlalu rapat, tool memperingatkan bila perkiraan
    jumlah level kontur lebih dari 2000.
  - Tool membutuhkan akses ke peta aktif, jadi tidak dijalankan di
    background.


---------------------------------------------------------------------
7. MEMBUAT ULANG TEMPLATE GAYA (ContourStyle.lyrx)
---------------------------------------------------------------------

Template bawaan memakai standar kartografi kontur:

  - Kontur index (IdxKontur = 1): garis 0.9 pt, coklat tua.
  - Kontur biasa (IdxKontur = 0): garis 0.3 pt, coklat muda.
  - Label hanya di kontur index: elevasi, Arial Bold 8 pt, coklat
    tua, halo putih 1.5 pt. Penempatan Maplex tipe Contour, teks
    tegak (mudah dibaca), diulang tiap ~250 pt di kontur panjang.
  - Jika Kontur index = 0, tool otomatis memakai satu simbol garis
    dan melabeli semua kontur.

Template ditulis langsung dalam format layer ArcGIS Pro dan belum
pernah dibuka di Pro. Jika layer gagal memuat template, tool memberi
peringatan dan memakai simbol bawaan dengan pola yang sama (index
tebal, biasa tipis). Untuk tampilan sesuai selera:

  1. Jalankan tool sekali, lalu atur simbol dan label layer kontur
     di Pro.
  2. Klik kanan layer > Sharing > Save As Layer File.
  3. Simpan sebagai ContourStyle.lyrx di folder toolbox ini
     (timpa file lama).

Jika template tidak ditemukan atau gagal dimuat, tool memakai simbol
bawaan ArcGIS dan label dari field Contour, disertai peringatan.


---------------------------------------------------------------------
8. PENYELESAIAN MASALAH
---------------------------------------------------------------------

"Definisi tool lama masih tersimpan di ArcGIS Pro"
    Klik kanan toolbox > Refresh, lalu buka ulang tool-nya.

Dropdown DEM kosong
    Tidak ada peta aktif atau tidak ada layer raster di peta. Tambahkan
    DEM ke peta, atau isi "Input DEM dari file".

"DEM belum punya sistem koordinat"
    Pilih CRS di isian "Sistem koordinat DEM" (misalnya WGS 1984 UTM
    Zone 50N sesuai lokasi data).

"Boundary tidak overlap dengan DEM"
    Periksa lokasi dan CRS boundary. Jika boundary tanpa CRS, pilih CRS
    yang benar di "Sistem koordinat boundary".

"Garis boundary tidak membentuk poligon tertutup"
    Tutup garis boundary, atau pakai layer poligon.

"Output ... sudah ada"
    Pakai nama output lain, atau aktifkan Overwrite di Options >
    Geoprocessing.

"Smooth Line gagal ... disimpan tanpa smoothing"
    Biasanya terkait lisensi. Hasil tetap tersimpan tanpa smoothing.

Tidak ada kontur tersisa
    Periksa interval, boundary, dan batas panjang noise (nilai terlalu
    besar bisa menghapus semua kontur).

Layer tidak muncul di peta
    Tidak ada peta aktif saat tool selesai. Kontur tetap tersimpan di
    lokasi output; tambahkan manual ke peta.

Label terlalu padat atau terlalu jarang
    Atur "Kontur index tiap": nilai lebih besar = label lebih jarang.
    Pengaturan ukuran teks dan pengulangan label ada di template
    (lihat bagian 7).

"Interval index sebaiknya kelipatan Contour interval"
    Contoh benar: interval 0.5, index tiap 5. Jika index bukan
    kelipatan interval, sebagian kontur index tidak akan muncul.


---------------------------------------------------------------------
9. RINGKASAN HASIL
---------------------------------------------------------------------

Tool menulis di jendela pesan geoprocessing: jumlah kontur yang
ditandai sebagai index, lalu setelah selesai jumlah kontur, rentang
elevasi, jumlah level, total panjang (km), dan lama proses.
