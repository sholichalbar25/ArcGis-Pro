# -*- coding: utf-8 -*-
"""Contour Tools (ArcGIS Pro) - kontur 1 klik dengan setelan bawaan ArcGIS.
Created by SHOLICH ALBAR

Target: ArcGIS Pro 2.x / 3.x (Python 3). Butuh extension Spatial Analyst.

Input: saat tool dibuka, semua layer di peta aktif dibaca dulu lalu ditampilkan di dropdown
(DEM = layer raster; boundary = layer poligon/garis). Kalau datanya belum ada di peta,
pakai isian 'dari file' (tombol browse); isian file diutamakan bila keduanya terisi.

Alur:
  1. Input DEM (+ boundary opsional, poligon atau garis tertutup) -> Extract by Mask
  2. Buat kontur            -> Spatial Analyst > Contour (base 0, Z factor 1)
  3. Haluskan kontur        -> Cartography > Smooth Line (PAEK)
  4. Hapus kontur noise     -> baca Shape_Length dari tabel atribut hasil (meter),
                               baris yang lebih kecil dari batas dihapus
  5. Pecah untuk label      -> kontur panjang dipecah otomatis jadi ruas-ruas sama panjang
                               (~50/100 m, atau otomatis dari ukuran area); tiap ruas punya
                               Shape_Length dan satu label sendiri, jadi label banyak tapi
                               tetap enak dibaca
  6. Label                  -> kontur index ditandai (field IdxKontur), layer ditambahkan ke
                               peta aktif: index tebal + berlabel, kontur biasa tipis
                               (gaya dari ContourStyle.lyrx di folder yang sama, bila ada)

CRS: DEM tanpa CRS -> pilih di 'Sistem koordinat DEM' (dipasang ke hasil kontur saja).
     Boundary tanpa CRS -> pilih di 'Sistem koordinat boundary' (dipasang ke salinan sementara).
     Data asli tidak pernah diubah.

Template gaya: atur simbol + label sebuah layer kontur di ArcGIS Pro, klik kanan layer >
Sharing > Save As Layer File, lalu simpan sebagai ContourStyle.lyrx di folder toolbox ini.
"""
import os
import time
import arcpy

STYLE_LYR = os.path.join(os.path.dirname(__file__), "ContourStyle.lyrx")
RASTER_EXT = (".tif", ".tiff", ".ecw", ".img", ".jp2", ".asc")
MAX_LEVELS_WARN = 2000
SEG_NICE = (50, 75, 100, 150, 200, 250, 300, 400, 500, 750, 1000, 1500, 2000, 2500, 5000)
SEG_MIN = 50  # ruas label otomatis tidak lebih pendek dari ini (meter)
NO_BND = "(tanpa boundary)"
INDEX_FIELD = "IdxKontur"
_LAYER_CACHE = {}  # {'raster'|'vector': [(label, Layer)]} dari saat dialog dibuka

(P_DEM_SEL, P_DEM, P_DEM_CRS, P_BND_SEL, P_BND, P_BND_CRS, P_OUT, P_INT, P_BASE, P_Z,
 P_LEN, P_CLOSED, P_TOL, P_IDX, P_SPLIT, P_SEG, P_LABEL, P_STYLE) = range(18)
N_PARAMS = 18
STALE_MSG = ("Definisi tool lama masih tersimpan di ArcGIS Pro. Tutup dialog ini, klik kanan "
             "toolbox 'Contour Tools' > Refresh, lalu buka ulang tool-nya.")


class Toolbox(object):
    def __init__(self):
        self.label = "Contour Tools"
        self.alias = "ContourTools"
        self.tools = [ContourOneClick]


class ContourOneClick(object):
    def __init__(self):
        self.label = "Kontur 1 Klik (DEM > Kontur > Haluskan > Bersihkan > Label)"
        self.description = (
            "Alur satu klik dengan setelan bawaan ArcGIS: pilih DEM dan boundary dari layer di "
            "peta (atau dari file), potong DEM, buat kontur, haluskan dengan Smooth Line, hapus "
            "kontur noise berdasarkan Shape_Length di tabel atribut, lalu tambahkan layer "
            "berlabel ke peta. Jarak dalam meter."
        )
        self.canRunInBackground = False  # perlu akses peta aktif (CURRENT)
        self._listed = False

    def getParameterInfo(self):
        self._listed = False  # dialog baru: baca ulang daftar layer peta
        adv = "Opsi kontur"
        lab = "Label"

        # --- DEM: dropdown layer peta + alternatif file
        p_dem_sel = arcpy.Parameter(
            displayName="Input DEM (pilih dari layer di peta)", name="dem_layer",
            datatype="GPString", parameterType="Optional", direction="Input")
        p_dem_sel.filter.type = "ValueList"
        p_dem_sel.filter.list = []

        p_dem = arcpy.Parameter(
            displayName="atau Input DEM dari file (kosongkan jika memakai layer peta)", name="in_dem",
            datatype="GPRasterLayer", parameterType="Optional", direction="Input")

        # isian CRS baru aktif (tidak abu-abu) kalau layer terkait memang belum punya CRS
        p_dem_crs = arcpy.Parameter(
            displayName="Sistem koordinat DEM (aktif jika DEM belum punya CRS)",
            name="dem_crs",
            datatype="GPSpatialReference", parameterType="Optional", direction="Input")
        p_dem_crs.enabled = False

        # --- Boundary: dropdown layer peta + alternatif file
        p_bnd_sel = arcpy.Parameter(
            displayName="Input boundary (pilih dari layer di peta)", name="boundary_layer",
            datatype="GPString", parameterType="Optional", direction="Input")
        p_bnd_sel.filter.type = "ValueList"
        p_bnd_sel.filter.list = [NO_BND]
        p_bnd_sel.value = NO_BND

        p_bnd = arcpy.Parameter(
            displayName="atau Input boundary dari file (poligon atau garis tertutup)", name="boundary",
            datatype="GPFeatureLayer", parameterType="Optional", direction="Input")
        p_bnd.filter.list = ["Polygon", "Polyline"]

        p_bnd_crs = arcpy.Parameter(
            displayName="Sistem koordinat boundary (aktif jika boundary belum punya CRS)",
            name="boundary_crs",
            datatype="GPSpatialReference", parameterType="Optional", direction="Input")
        p_bnd_crs.enabled = False

        p_out = arcpy.Parameter(
            displayName="Output kontur", name="out_contour",
            datatype="DEFeatureClass", parameterType="Required", direction="Output")

        p_int = arcpy.Parameter(
            displayName="Contour interval (satuan Z)", name="interval",
            datatype="GPDouble", parameterType="Required", direction="Input")
        p_int.value = 0.5

        p_base = arcpy.Parameter(
            displayName="Base contour", name="base",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        p_base.value = 0
        p_base.category = adv

        p_z = arcpy.Parameter(
            displayName="Z factor (1 = tidak diubah, 0.3048 untuk feet ke meter)", name="z_factor",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        p_z.value = 1
        p_z.category = adv

        p_len = arcpy.Parameter(
            displayName="Hapus kontur dengan Shape_Length lebih kecil dari (meter, 0 = lewati)",
            name="min_length",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        p_len.value = 20
        p_len.category = adv

        p_closed = arcpy.Parameter(
            displayName="Hapus hanya loop tertutup (jika dicentang, garis pendek terbuka di tepi DEM dipertahankan)",
            name="only_closed",
            datatype="GPBoolean", parameterType="Optional", direction="Input")
        p_closed.value = False
        p_closed.category = adv

        p_tol = arcpy.Parameter(
            displayName="Smoothing tolerance (kosongkan untuk tanpa smoothing)", name="smooth_tol",
            datatype="GPLinearUnit", parameterType="Optional", direction="Input")
        p_tol.value = "3 Meters"
        p_tol.category = adv

        p_idx = arcpy.Parameter(
            displayName="Kontur index tiap (satuan Z, 0 = tanpa index; hanya kontur index yang dilabeli)",
            name="index_every",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        p_idx.value = 5
        p_idx.category = lab

        p_split = arcpy.Parameter(
            displayName="Pecah kontur panjang jadi ruas-ruas agar labelnya banyak (tiap ruas punya Shape_Length dan label sendiri)",
            name="split_for_labels",
            datatype="GPBoolean", parameterType="Optional", direction="Input")
        p_split.value = True
        p_split.category = lab

        p_seg = arcpy.Parameter(
            displayName="Panjang ruas (meter, mis. 50 atau 100; 0 = otomatis dari ukuran area)",
            name="segment_length",
            datatype="GPDouble", parameterType="Optional", direction="Input")
        p_seg.value = 0
        p_seg.category = lab

        p_label = arcpy.Parameter(
            displayName="Tambahkan ke peta dan label", name="add_labels",
            datatype="GPBoolean", parameterType="Optional", direction="Input")
        p_label.value = True
        p_label.category = lab

        p_style = arcpy.Parameter(
            displayName="Template gaya (.lyrx) - simbol dan label", name="style_lyr",
            datatype="DEFile", parameterType="Optional", direction="Input")
        p_style.filter.list = ["lyrx"]
        if os.path.isfile(STYLE_LYR):
            p_style.value = STYLE_LYR
        p_style.category = lab

        return [p_dem_sel, p_dem, p_dem_crs, p_bnd_sel, p_bnd, p_bnd_crs, p_out, p_int,
                p_base, p_z, p_len, p_closed, p_tol, p_idx, p_split, p_seg, p_label, p_style]

    def isLicensed(self):
        try:
            return arcpy.CheckExtension("Spatial") == "Available"
        except Exception:
            return False

    def updateParameters(self, parameters):
        if len(parameters) != N_PARAMS:
            return

        dem_sel, dem_file = parameters[P_DEM_SEL], parameters[P_DEM]
        bnd_sel, bnd_file = parameters[P_BND_SEL], parameters[P_BND]

        # baca semua layer di peta aktif sekali (saat dialog dibuka) untuk mengisi dropdown
        if not self._listed:
            self._listed = True
            rasters = _map_layers("raster")
            dem_sel.filter.list = [lbl for lbl, _ in rasters]
            if not dem_sel.value and not dem_sel.altered and rasters:
                visible = [lbl for lbl, lyr in rasters if lyr.visible]
                dem_sel.value = (visible or [rasters[0][0]])[0]
            bnd_sel.filter.list = [NO_BND] + [lbl for lbl, _ in _map_layers("vector")]

        # isian CRS DEM aktif hanya kalau DEM belum punya CRS (gagal baca = aktifkan saja)
        if not dem_sel.hasBeenValidated or not dem_file.hasBeenValidated:
            ref = _pick(dem_sel, dem_file, "raster")
            if ref:
                try:
                    parameters[P_DEM_CRS].enabled = (arcpy.Describe(ref).spatialReference.name == "Unknown")
                except Exception:
                    parameters[P_DEM_CRS].enabled = True
                # nama output otomatis dari DEM (di workspace bawaan proyek)
                if not parameters[P_OUT].altered:
                    try:
                        name = _default_name(_name_of(ref))
                        ws = arcpy.env.workspace or arcpy.env.scratchGDB
                        parameters[P_OUT].value = arcpy.CreateUniqueName(
                            arcpy.ValidateTableName(name, ws), ws)
                    except Exception:
                        pass
            else:
                parameters[P_DEM_CRS].enabled = False

        if not bnd_sel.hasBeenValidated or not bnd_file.hasBeenValidated:
            ref = _pick(bnd_sel, bnd_file, "vector")
            if ref:
                try:
                    parameters[P_BND_CRS].enabled = (arcpy.Describe(ref).spatialReference.name == "Unknown")
                except Exception:
                    parameters[P_BND_CRS].enabled = True
            else:
                parameters[P_BND_CRS].enabled = False
        return

    def updateMessages(self, parameters):
        if len(parameters) != N_PARAMS:
            parameters[0].setErrorMessage(STALE_MSG)
            return
        dem_ref = _pick(parameters[P_DEM_SEL], parameters[P_DEM], "raster")
        if dem_ref is None:
            parameters[P_DEM_SEL].setErrorMessage(
                "Pilih DEM dari daftar layer di peta, atau isi 'Input DEM dari file'.")
        else:
            if parameters[P_DEM_CRS].enabled and not parameters[P_DEM_CRS].value:
                parameters[P_DEM_CRS].setErrorMessage(
                    "DEM ini belum punya sistem koordinat. Pilih sistem koordinat "
                    "(mis. WGS 1984 UTM Zone 50N).")
            try:
                if getattr(arcpy.Describe(dem_ref), "bandCount", 1) > 1:
                    parameters[P_DEM_SEL].setErrorMessage("DEM harus satu band (bukan citra multiband/RGB).")
            except Exception:
                pass
        if parameters[P_DEM].value and parameters[P_DEM_SEL].value:
            parameters[P_DEM_SEL].setWarningMessage(
                "Isian 'DEM dari file' terisi, jadi file itu yang dipakai, bukan layer peta.")
        if parameters[P_BND_CRS].enabled and not parameters[P_BND_CRS].value:
            parameters[P_BND_CRS].setWarningMessage(
                "Boundary ini belum punya sistem koordinat. Pilih CRS boundary-nya; "
                "jika dikosongkan, dianggap sama dengan CRS DEM.")
        if parameters[P_INT].value is not None and parameters[P_INT].value <= 0:
            parameters[P_INT].setErrorMessage("Contour interval harus lebih besar dari 0.")
        if parameters[P_Z].value is not None and parameters[P_Z].value <= 0:
            parameters[P_Z].setErrorMessage("Z factor harus lebih besar dari 0.")
        if parameters[P_LEN].value is not None and parameters[P_LEN].value < 0:
            parameters[P_LEN].setErrorMessage("Panjang minimum tidak boleh negatif.")
        if parameters[P_SEG].value is not None and parameters[P_SEG].value < 0:
            parameters[P_SEG].setErrorMessage("Panjang ruas tidak boleh negatif.")
        idx, itv = parameters[P_IDX].value, parameters[P_INT].value
        if idx is not None and idx < 0:
            parameters[P_IDX].setErrorMessage("Interval index tidak boleh negatif.")
        elif idx and itv and itv > 0:
            ratio = idx / itv
            if ratio < 1 - 1e-6 or abs(ratio - round(ratio)) > 1e-6:
                parameters[P_IDX].setWarningMessage(
                    "Interval index sebaiknya kelipatan Contour interval; jika tidak, "
                    "sebagian kontur index tidak akan muncul.")
        return

    def execute(self, parameters, messages):
        if len(parameters) != N_PARAMS:
            raise ValueError(STALE_MSG)

        from arcpy import sa

        t_start = time.time()
        in_dem = _pick(parameters[P_DEM_SEL], parameters[P_DEM], "raster", fresh=True)
        if in_dem is None:
            raise ValueError("DEM belum dipilih. Pilih dari daftar layer di peta atau isi dari file.")
        boundary = _pick(parameters[P_BND_SEL], parameters[P_BND], "vector", fresh=True)
        if boundary is None and parameters[P_BND_SEL].valueAsText not in (None, NO_BND) \
                and not parameters[P_BND].value:
            raise ValueError("Layer boundary '{0}' tidak ditemukan di peta aktif.".format(
                parameters[P_BND_SEL].valueAsText))
        out_fc = parameters[P_OUT].valueAsText
        interval = float(parameters[P_INT].value)
        base = float(parameters[P_BASE].value) if parameters[P_BASE].value is not None else 0.0
        z_factor = float(parameters[P_Z].value) if parameters[P_Z].value else 1.0
        min_len_m = float(parameters[P_LEN].value) if parameters[P_LEN].value else 0.0
        only_closed = bool(parameters[P_CLOSED].value)
        tol_text = parameters[P_TOL].valueAsText
        idx_every = float(parameters[P_IDX].value) if parameters[P_IDX].value else 0.0
        split_labels = bool(parameters[P_SPLIT].value)
        seg_m = float(parameters[P_SEG].value) if parameters[P_SEG].value else 0.0
        add_labels = bool(parameters[P_LABEL].value)
        style = parameters[P_STYLE].valueAsText

        if getattr(arcpy.Describe(in_dem), "bandCount", 1) > 1:
            raise ValueError("DEM harus satu band (bukan citra multiband/RGB).")

        # CRS DEM: pakai milik DEM; kalau belum ada, pakai pilihan pengguna
        dem_sr = arcpy.Describe(in_dem).spatialReference
        dem_has_crs = dem_sr.name != "Unknown"
        if dem_has_crs:
            sr = dem_sr
        else:
            sr = _to_sr(parameters[P_DEM_CRS])
            if sr is None or sr.name == "Unknown":
                raise ValueError("DEM belum punya sistem koordinat. Pilih sistem koordinat "
                                 "di isian 'Sistem koordinat DEM' (mis. WGS 1984 UTM Zone 50N).")
            arcpy.AddWarning("DEM belum punya CRS; koordinatnya dianggap {0}. DEM asli tidak diubah, "
                             "CRS dipasang ke hasil kontur.".format(sr.name))
        if sr.type == "Projected":
            mpu = sr.metersPerUnit or 1.0
            if abs(mpu - 1.0) > 1e-9:
                arcpy.AddWarning("Satuan CRS bukan meter (1 unit = {0:.4f} m); panjang minimum "
                                 "dikonversi otomatis.".format(mpu))
        else:
            arcpy.AddWarning("CRS DEM geografis (derajat). Panjang kontur dihitung geodesik dalam meter; "
                             "CRS proyeksi (mis. UTM) lebih disarankan.")

        # CRS boundary (hanya dipakai kalau boundary-nya sendiri belum punya CRS)
        bnd_sr = None
        if boundary is not None and parameters[P_BND_CRS].value:
            bnd_sr = _to_sr(parameters[P_BND_CRS])
            if bnd_sr is not None and bnd_sr.name == "Unknown":
                bnd_sr = None

        if arcpy.CheckOutExtension("Spatial") != "CheckedOut":
            raise RuntimeError("Extension Spatial Analyst tidak tersedia.")
        old_overwrite = arcpy.env.overwriteOutput
        if arcpy.Exists(out_fc) and not old_overwrite:
            arcpy.CheckInExtension("Spatial")
            raise ValueError("Output '{0}' sudah ada. Pakai nama lain, atau aktifkan Overwrite "
                             "(Options > Geoprocessing) agar bisa ditimpa.".format(out_fc))
        arcpy.env.overwriteOutput = True  # hanya agar file sementara bisa ditimpa

        scratch = arcpy.env.scratchGDB
        tmp_contour = arcpy.CreateUniqueName("tmp_contour_raw", scratch)
        temps = [tmp_contour]
        try:
            dem = sa.Raster(in_dem)

            # perkiraan jumlah level kontur, supaya tidak kebablasan pada interval terlalu rapat
            try:
                zmin, zmax = dem.minimum * z_factor, dem.maximum * z_factor
                levels = int((zmax - zmin) / interval) + 1
                arcpy.AddMessage("      Elevasi DEM {0:.2f} s/d {1:.2f}; perkiraan {2} level kontur.".format(
                    zmin, zmax, levels))
                if levels > MAX_LEVELS_WARN:
                    arcpy.AddWarning("Perkiraan {0} level kontur sangat banyak. Periksa interval "
                                     "dan Z factor.".format(levels))
            except Exception:
                pass

            # cell size vs toleransi smoothing (efek PAEK minim jika toleransi < cell size)
            try:
                cell_m = dem.meanCellWidth * (sr.metersPerUnit or 1.0) if sr.type == "Projected" else None
                if cell_m:
                    arcpy.AddMessage("      Cell size DEM {0:.3f} m.".format(cell_m))
                    if "meter" in (tol_text or "").lower() and 0 < _linear_value(tol_text) < cell_m:
                        arcpy.AddWarning("Smoothing tolerance ({0}) lebih kecil dari cell size DEM; "
                                         "efek penghalusan akan minim.".format(tol_text))
            except Exception:
                pass

            # 1. Potong DEM sesuai boundary
            if boundary is not None:
                _step(1, "Menyiapkan boundary dan memotong DEM: {0}".format(_name_of(boundary)))
                bnd = _prepare_boundary(boundary, sr, scratch, temps, bnd_sr)
                if not _extents_overlap(arcpy.Describe(bnd).extent, dem.extent):
                    raise ValueError("Boundary tidak overlap dengan DEM. Cek CRS dan lokasinya.")
                dem = sa.ExtractByMask(dem, bnd)
            else:
                _step(1, "Tanpa boundary, seluruh DEM dipakai.")

            # 2. Kontur
            _step(2, "Membuat kontur (interval {0}, base {1}, Z factor {2})...".format(
                interval, base, z_factor))
            sa.Contour(dem, tmp_contour, interval, base, z_factor)
            if not dem_has_crs:
                arcpy.management.DefineProjection(tmp_contour, sr)
            arcpy.AddMessage("      {0} kontur dihasilkan.".format(_count(tmp_contour)))

            # 3. Haluskan garis
            if tol_text and _linear_value(tol_text) > 0:
                _step(3, "Smooth Line (PAEK), toleransi {0}...".format(tol_text))
                try:
                    arcpy.cartography.SmoothLine(tmp_contour, out_fc, "PAEK", tol_text)
                except arcpy.ExecuteError:
                    # mis. lisensi Smooth Line tidak tersedia: jangan gagalkan seluruh proses
                    arcpy.AddWarning("Smooth Line gagal ({0}); kontur disimpan tanpa smoothing.".format(
                        arcpy.GetMessages(2).strip().replace("\n", " | ")))
                    arcpy.management.CopyFeatures(tmp_contour, out_fc)
            else:
                _step(3, "Tanpa smoothing, menyalin kontur...")
                arcpy.management.CopyFeatures(tmp_contour, out_fc)

            # 4. Hapus noise: baca Shape_Length dari tabel atribut hasil, lalu hapus barisnya
            if min_len_m > 0:
                before = _count(out_fc)
                removed = _remove_short(out_fc, min_len_m, only_closed, sr)
                _step(4, "Hapus noise: {0} dari {1} baris atribut dihapus (Shape_Length < {2} m{3}).".format(
                    removed, before, min_len_m, ", hanya loop tertutup" if only_closed else ""))
            else:
                _step(4, "Hapus noise dilewati.")
            final = _count(out_fc)
            if final == 0:
                arcpy.AddWarning("Tidak ada kontur yang tersisa. Cek boundary, interval, dan batas panjang noise.")
            arcpy.AddMessage("      Tersimpan: {0} ({1} kontur).".format(out_fc, final))
            use_index = False
            if idx_every > 0 and final > 0:
                use_index = _mark_index(out_fc, base, idx_every)
            _summary(out_fc, sr)

            # 5. Pecah kontur panjang jadi ruas-ruas: tiap ruas punya Shape_Length dan label sendiri
            if split_labels and final > 0:
                seg = seg_m if seg_m > 0 else _auto_segment_m(out_fc, sr)
                _step(5, "Memecah kontur panjang jadi ruas ~{0:g} m agar label banyak ({1})...".format(
                    seg, "manual" if seg_m > 0 else "otomatis dari ukuran area"))
                n_in, n_out = _split_for_labels(out_fc, seg, sr)
                arcpy.AddMessage("      {0} kontur -> {1} ruas (atribut tiap ruas ikut disalin).".format(
                    n_in, n_out))
            else:
                _step(5, "Pemecahan kontur dilewati.")

            # 6. Layer berlabel
            if add_labels and final > 0:
                _step(6, "Menambahkan layer berlabel ke peta...")
                _add_layer_with_labels(out_fc, style, use_index)
            else:
                _step(6, "Penambahan layer dan label dilewati.")
            arcpy.AddMessage("Selesai dalam {0:.1f} detik.".format(time.time() - t_start))
        finally:
            arcpy.ResetProgressor()
            for t in temps:
                try:
                    if arcpy.Exists(t):
                        arcpy.management.Delete(t)
                except Exception:
                    pass
            arcpy.env.overwriteOutput = old_overwrite
            arcpy.CheckInExtension("Spatial")
        return


# ---------------------------------------------------------------- helpers

def _step(n, text):
    msg = "[{0}/6] {1}".format(n, text)
    arcpy.SetProgressorLabel(msg)
    arcpy.AddMessage(msg)


def _map_layers(kind):
    """Baca semua layer di peta aktif ArcGIS Pro -> [(label unik, objek Layer)].

    kind 'raster' = layer raster; 'vector' = layer fitur poligon/garis.
    Layer rusak dan group layer dilewati; nama kembar diberi nomor urut.
    """
    out = []
    _LAYER_CACHE[kind] = out
    try:
        m = arcpy.mp.ArcGISProject("CURRENT").activeMap
        if m is None:
            return out
        seen = {}
        for lyr in m.listLayers():
            if lyr.isGroupLayer or getattr(lyr, "isBroken", False):
                continue
            if kind == "raster":
                ok = lyr.isRasterLayer
            else:
                ok = False
                if lyr.isFeatureLayer:
                    try:
                        ok = arcpy.Describe(lyr).shapeType in ("Polygon", "Polyline")
                    except Exception:
                        ok = False
            if not ok:
                continue
            seen[lyr.name] = seen.get(lyr.name, 0) + 1
            label = lyr.name if seen[lyr.name] == 1 else "{0} ({1})".format(lyr.name, seen[lyr.name])
            out.append((label, lyr))
    except Exception:
        pass
    return out


def _pick(sel_param, file_param, kind, fresh=False):
    """Input terpilih: isian file diutamakan, lalu layer dari dropdown peta; None jika kosong.

    DEM dikembalikan sebagai path sumber datanya; boundary sebagai objek Layer
    (supaya seleksi fitur di peta ikut terbaca) atau path bila dari file.
    Daftar layer memakai cache dari saat dialog dibuka (cepat); `fresh=True` (saat eksekusi)
    atau cache meleset -> peta dibaca ulang.
    """
    if file_param.value:
        return file_param.valueAsText
    label = sel_param.valueAsText
    if not label or label == NO_BND:
        return None
    reloaded = fresh
    layers = None if fresh else _LAYER_CACHE.get(kind)
    while True:
        if layers is None:
            layers = _map_layers(kind)
            reloaded = True
        for lbl, lyr in layers:
            if lbl == label:
                try:
                    lyr.name  # objek Layer basi (proyek berubah) -> error -> baca ulang peta
                    return lyr.dataSource if kind == "raster" else lyr
                except Exception:
                    break
        if reloaded:
            return None
        layers = None


def _name_of(ref):
    """Nama tampilan untuk path atau objek Layer."""
    try:
        return ref.name
    except AttributeError:
        return os.path.basename(str(ref))


def _default_name(layer_name):
    base, ext = os.path.splitext(layer_name)
    if ext.lower() not in RASTER_EXT:
        base = layer_name
    return base + "_Kontur"


def _linear_value(text):
    """Ambil angka dari string linear unit, mis. '3 Meters' atau '3,5 Meters'."""
    try:
        return float(text.split()[0].replace(",", "."))
    except (ValueError, IndexError, AttributeError):
        return 0.0


def _to_sr(param):
    """Ambil SpatialReference dari parameter GPSpatialReference (objek atau teks WKT)."""
    v = param.value
    if v is None:
        return None
    if hasattr(v, "type") and hasattr(v, "name"):
        return v
    sr = arcpy.SpatialReference()
    sr.loadFromString(param.valueAsText)
    return sr


def _extents_overlap(a, b):
    return not (a.XMax < b.XMin or b.XMax < a.XMin or a.YMax < b.YMin or b.YMax < a.YMin)


def _count(fc):
    return int(arcpy.management.GetCount(fc).getOutput(0))


def _prepare_boundary(boundary, sr, scratch, temps, bnd_sr=None):
    """Siapkan boundary untuk memotong DEM.

    - Belum punya CRS: pasang `bnd_sr` (pilihan pengguna; kosong = dianggap sama dengan DEM)
      pada salinan sementara, data asli tidak diubah.
    - CRS beda dengan DEM: di-project ke CRS DEM.
    - Garis tertutup diubah jadi poligon; semua fitur di-dissolve jadi satu bentuk.
    Fitur yang sedang terpilih di layer boundary (jika ada) otomatis dipakai saja.
    Mengembalikan path feature class hasil; semua temp dicatat di `temps`.
    """
    desc = arcpy.Describe(boundary)
    shape = desc.shapeType
    if shape not in ("Polygon", "Polyline"):
        raise ValueError("Boundary harus berupa poligon atau garis tertutup, bukan {0}.".format(shape))
    src = boundary

    bsr = desc.spatialReference
    if bsr.name == "Unknown":
        assumed = bnd_sr if bnd_sr is not None else sr
        if bnd_sr is not None:
            arcpy.AddMessage("      Boundary belum punya CRS; dipasang {0} (hanya pada salinan).".format(assumed.name))
        else:
            arcpy.AddMessage("      Boundary belum punya CRS; dianggap sama dengan DEM ({0}).".format(assumed.name))
        defined = arcpy.CreateUniqueName("tmp_boundary_def", scratch)
        temps.append(defined)
        arcpy.management.CopyFeatures(src, defined)
        arcpy.management.DefineProjection(defined, assumed)
        src = defined
        bsr = assumed

    if bsr.name != sr.name:
        arcpy.AddMessage("      Reproject boundary dari {0} ke {1}.".format(bsr.name, sr.name))
        proj = arcpy.CreateUniqueName("tmp_boundary_proj", scratch)
        temps.append(proj)
        arcpy.management.Project(src, proj, sr)
        src = proj

    if shape == "Polyline":
        poly = arcpy.CreateUniqueName("tmp_boundary_poly", scratch)
        temps.append(poly)
        arcpy.management.FeatureToPolygon(src, poly)
        if _count(poly) == 0:
            raise ValueError("Garis boundary tidak membentuk poligon tertutup. "
                             "Tutup garisnya, atau pakai layer poligon.")
        src = poly

    diss = arcpy.CreateUniqueName("tmp_boundary_diss", scratch)
    temps.append(diss)
    arcpy.management.Dissolve(src, diss)
    if _count(diss) == 0:
        raise ValueError("Boundary kosong. Cek layer boundary dan seleksinya.")
    return diss


def _summary(fc, sr):
    """Ringkasan hasil: jumlah kontur, rentang elevasi, total panjang (km)."""
    try:
        z_field = next((f.name for f in arcpy.ListFields(fc) if f.name.lower() == "contour"), None)
        fields = ["SHAPE@LENGTH"] + ([z_field] if z_field else [])
        n, total_len, zs = 0, 0.0, []
        with arcpy.da.SearchCursor(fc, fields) as cur:
            for row in cur:
                n += 1
                total_len += row[0] or 0.0
                if z_field and row[1] is not None:
                    zs.append(row[1])
        if sr.type == "Projected":
            total_len *= (sr.metersPerUnit or 1.0)
        else:
            total_len = 0.0
        msg = "      Ringkasan: {0} kontur".format(n)
        if zs:
            msg += ", elevasi {0:g} s/d {1:g}, {2} level".format(min(zs), max(zs), len(set(zs)))
        if total_len:
            msg += ", total panjang {0:.2f} km".format(total_len / 1000.0)
        arcpy.AddMessage(msg + ".")
    except Exception:
        pass


def _is_closed(geom):
    p1, p2 = geom.firstPoint, geom.lastPoint
    return abs(p1.X - p2.X) < 1e-6 and abs(p1.Y - p2.Y) < 1e-6


def _length_field(fc):
    """Nama field panjang di tabel atribut (Shape_Length / Shape_Leng); None jika tidak ada."""
    for f in arcpy.ListFields(fc):
        if f.name.lower() in ("shape_length", "shape_leng"):
            return f.name
    return None


def _remove_short(fc, min_len_m, only_closed, sr):
    """Hapus baris atribut yang Shape_Length (Shape_Leng di shapefile) lebih kecil dari min_len_m meter.

    CRS proyeksi: nilai dibaca langsung dari field Shape_Length di tabel atribut; hanya baris
    dengan nilai di bawah ambang yang diproses (ambang dikonversi dari meter ke satuan CRS).
    CRS geografis: panjang dihitung geodesik dalam meter dari geometrinya.
    """
    projected = sr.type == "Projected"
    len_field = None
    threshold = min_len_m
    if projected:
        threshold = min_len_m / (sr.metersPerUnit or 1.0)
        len_field = _length_field(fc) or "SHAPE@LENGTH"
    fields = ([len_field] if len_field else []) + ["SHAPE@"]
    where = None
    if len_field and not len_field.startswith("SHAPE@"):
        where = "{0} < {1!r}".format(arcpy.AddFieldDelimiters(fc, len_field), float(threshold))
    removed = 0
    with arcpy.da.UpdateCursor(fc, fields, where) as cur:
        for row in cur:
            geom = row[-1]
            if geom is None:
                cur.deleteRow()
                removed += 1
                continue
            if len_field:
                length = row[0]
            else:
                try:
                    length = geom.getLength("GEODESIC", "METERS")
                except Exception:
                    length = geom.length
            if length is not None and length < threshold and (not only_closed or _is_closed(geom)):
                cur.deleteRow()
                removed += 1
    return removed


def _connection_of(out_fc):
    """(folder/gdb, dataset, workspace_factory) untuk template .lyrx; None jika tidak dikenali."""
    low = out_fc.lower()
    if ".gdb" in low:
        i = low.index(".gdb") + 4
        return out_fc[:i], os.path.basename(out_fc), "File Geodatabase"
    if low.endswith(".shp"):
        return os.path.dirname(out_fc), os.path.basename(out_fc), "Shape File"
    return None


def _mark_index(fc, base, idx_every):
    """Tambah field IdxKontur (1 = kontur index, 0 = biasa). True jika berhasil."""
    fields = [f.name for f in arcpy.ListFields(fc)]
    z_field = next((f for f in fields if f.lower() == "contour"), None)
    if z_field is None:
        arcpy.AddWarning("Field 'Contour' tidak ditemukan; kontur index tidak ditandai.")
        return False
    if INDEX_FIELD not in fields:
        arcpy.management.AddField(fc, INDEX_FIELD, "SHORT")
    n_idx = 0
    with arcpy.da.UpdateCursor(fc, [z_field, INDEX_FIELD]) as cur:
        for z, _ in cur:
            flag = 0
            if z is not None:
                r = (z - base) / idx_every
                if abs(r - round(r)) < 1e-4:
                    flag = 1
            n_idx += flag
            cur.updateRow([z, flag])
    arcpy.AddMessage("      {0} kontur ditandai sebagai index (tiap {1}).".format(n_idx, idx_every))
    return True


def _style_single(lyr):
    """Satu simbol garis untuk semua kontur (dipakai bila tanpa kontur index)."""
    sym = lyr.symbology
    sym.updateRenderer("SimpleRenderer")
    sym.renderer.symbol.color = {"RGB": [150, 100, 50, 100]}
    sym.renderer.symbol.size = 0.5
    lyr.symbology = sym


def _style_default(lyr, use_index):
    """Simbol bawaan tanpa template: index tebal coklat tua, biasa tipis coklat muda."""
    if not use_index:
        _style_single(lyr)
        return
    sym = lyr.symbology
    sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = [INDEX_FIELD]
    for group in sym.renderer.groups:
        for item in group.items:
            is_idx = str(item.values[0][0]) == "1"
            item.label = "Kontur index" if is_idx else "Kontur biasa"
            item.symbol.color = {"RGB": [122, 74, 30, 100]} if is_idx else {"RGB": [196, 146, 96, 100]}
            item.symbol.size = 0.9 if is_idx else 0.3
    lyr.symbology = sym


def _auto_segment_m(fc, sr):
    """Panjang ruas label otomatis (meter): ~1/6 sisi terpanjang area kontur, dibulatkan ke
    angka 'enak' (50, 75, 100, 150, ...), minimal SEG_MIN. Area 600 m -> 100 m, 1.2 km -> 200 m.
    CRS geografis (ukuran meter tidak diketahui) -> 100 m.
    """
    try:
        if sr.type != "Projected":
            return 100.0
        ext = arcpy.Describe(fc).extent
        span_m = max(ext.XMax - ext.XMin, ext.YMax - ext.YMin) * (sr.metersPerUnit or 1.0)
        target = max(span_m / 6.0, SEG_MIN)
        return float(min(SEG_NICE, key=lambda v: abs(v - target)))
    except Exception:
        return 100.0


def _split_for_labels(fc, seg_m, sr):
    """Pecah kontur panjang jadi ruas-ruas (~seg_m meter) supaya tiap ruas punya label sendiri.

    Kontur sepanjang L dipecah jadi n = round(L / seg_m) ruas SAMA panjang (tanpa sisa
    pendek, tiap ruas 0.75-1.5 x seg_m); kontur < 1.5 x seg_m tidak dipecah. Semua atribut
    (Contour, IdxKontur, dst.) disalin ke tiap ruas; Shape_Length dihitung ulang per ruas.
    Mengembalikan (jumlah kontur sebelum, jumlah ruas sesudah).
    """
    desc = arcpy.Describe(fc)
    fields = [f.name for f in arcpy.ListFields(fc)
              if f.type not in ("OID", "Geometry")
              and f.name.lower() not in ("shape_length", "shape_leng", "shape_area")]
    cols = fields + ["SHAPE@"]
    mpu = (sr.metersPerUnit or 1.0) if sr.type == "Projected" else None

    tmp = arcpy.CreateUniqueName("tmp_split", arcpy.env.scratchGDB)
    arcpy.management.CreateFeatureclass(os.path.dirname(tmp), os.path.basename(tmp), "POLYLINE",
                                        fc, spatial_reference=desc.spatialReference)
    n_in = n_out = 0
    try:
        with arcpy.da.InsertCursor(tmp, cols) as ins, arcpy.da.SearchCursor(fc, cols) as src:
            for row in src:
                geom = row[-1]
                if geom is None:
                    continue
                n_in += 1
                if mpu is not None:
                    length_m = geom.length * mpu
                else:
                    try:
                        length_m = geom.getLength("GEODESIC", "METERS")
                    except Exception:
                        length_m = 0.0
                n = int(length_m / seg_m + 0.5)
                if n < 2:
                    ins.insertRow(row)
                    n_out += 1
                    continue
                attrs = list(row[:-1])
                for i in range(n):
                    part = geom.segmentAlongLine(i / float(n), (i + 1) / float(n), True)
                    ins.insertRow(attrs + [part])
                    n_out += 1
        arcpy.management.CopyFeatures(tmp, fc)  # timpa dengan versi ber-ruas (overwrite aktif)
    finally:
        try:
            if arcpy.Exists(tmp):
                arcpy.management.Delete(tmp)
        except Exception:
            pass
    return n_in, n_out


def _label_where(fc, use_index):
    """Filter label: hanya kontur index (IdxKontur = 1); kosong = semua kontur dilabeli."""
    if use_index:
        return "{0} = 1".format(arcpy.AddFieldDelimiters(fc, INDEX_FIELD))
    return ""


def _add_layer_with_labels(out_fc, template, use_index):
    """Tambahkan kontur ke peta aktif, lengkap dengan simbol dan label.

    use_index True: simbol index/biasa dari field IdxKontur dan hanya kontur index yang dilabeli.
    use_index False: satu simbol untuk semua kontur dan semua kontur dilabeli.
    Banyaknya label datang dari pemecahan kontur jadi ruas (_split_for_labels): tiap ruas = satu label.
    """
    try:
        m = arcpy.mp.ArcGISProject("CURRENT").activeMap
        if m is None:
            raise RuntimeError("tidak ada peta aktif")
    except Exception:
        arcpy.AddWarning("Tidak ada peta aktif di ArcGIS Pro. Kontur sudah tersimpan, "
                         "tapi layer tidak ditambahkan ke peta.")
        return

    lyr = None
    has_template = bool(template and os.path.isfile(template))
    conn = _connection_of(out_fc)
    if has_template and conn:
        # layer dari template .lyrx: simbol dan semua properti label (Maplex, halo, dst.) ikut terbawa
        try:
            tl = arcpy.mp.LayerFile(template).listLayers()[0]
            tl.updateConnectionProperties(tl.connectionProperties, {
                "dataset": conn[1],
                "workspace_factory": conn[2],
                "connection_info": {"database": conn[0]}})
            lyr = m.addLayer(tl, "TOP")[0]
            arcpy.AddMessage("      Gaya dari template: {0}".format(template))
            if not use_index:
                _style_single(lyr)  # template merujuk IdxKontur yang tidak dibuat
        except Exception as e:
            arcpy.AddWarning("Template .lyrx gagal dipakai langsung ({0}); mencoba terapkan simbologinya.".format(e))
            lyr = None

    if lyr is None:
        lyr = m.addDataFromPath(out_fc)
        styled = False
        if has_template:
            try:
                arcpy.management.ApplySymbologyFromLayer(lyr, template)
                styled = True
                if not use_index:
                    _style_single(lyr)
            except Exception as e:
                arcpy.AddWarning("Simbologi template gagal diterapkan ({0}); memakai gaya bawaan.".format(e))
        else:
            arcpy.AddWarning("Template ContourStyle.lyrx tidak ditemukan: memakai simbol dan label bawaan.")
        if not styled:
            try:
                _style_default(lyr, use_index)
            except Exception as e:
                arcpy.AddWarning("Simbol bawaan gagal diterapkan ({0}); memakai simbol default ArcGIS.".format(e))
        for lc in lyr.listLabelClasses():
            lc.expressionEngine = "Arcade"
            lc.expression = "Round($feature.Contour, 2)"

    where = _label_where(out_fc, use_index)
    for lc in lyr.listLabelClasses():
        lc.SQLQuery = where  # filter label (kosong = semua kontur dilabeli)
        lc.visible = True
    lyr.showLabels = True
