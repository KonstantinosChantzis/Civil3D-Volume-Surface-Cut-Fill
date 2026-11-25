"""Auswertung des LandXML-Exports aus Civil 3D (ID 57, Volume Surface).

Liest die Flaechen Planum (Grading) und DGM_Bestand aus data/ID57_Volumenflaeche.xml,
berechnet Abtrag und Auftrag unabhaengig von Civil 3D (Rastermethode, wie eine
TIN-Volume-Surface) und erzeugt Kennzahlen, eine Schnitttabelle und zwei Grafiken.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.tri as mtri
from matplotlib.colors import BoundaryNorm, ListedColormap

ROOT = Path(__file__).resolve().parents[1]
XML = ROOT / "data" / "ID57_Volumenflaeche.xml"
RES = ROOT / "results"
IMG = ROOT / "images"
NS = {"l": "http://www.landxml.org/schema/LandXML-1.2"}
CELL = 0.10                     # Rasterweite fuer die Massenberechnung (m)
CIVIL3D = {"cut": 1762.58, "fill": 1821.96}   # Volumes Dashboard (m3)
PLANUM = 88.20                  # Hoehe der Planumsflaeche (m)
CX, CY = 366120.0, 5702470.0    # Mitte der Flaeche 60 x 40 m


def read_surface(root, name):
    surf = root.find(f".//l:Surface[@name='{name}']", NS)
    sdef = surf.find("l:Definition", NS)
    ids, xyz = {}, []
    for i, p in enumerate(sdef.findall("l:Pnts/l:P", NS)):
        n, e, z = (float(v) for v in p.text.split())   # LandXML: Nord Ost Hoehe
        ids[p.get("id")] = i
        xyz.append((e, n, z))
    xyz = np.array(xyz)
    faces = [[ids[v] for v in f.text.split()]
             for f in sdef.findall("l:Faces/l:F", NS) if f.get("i") != "1"]
    tri = mtri.Triangulation(xyz[:, 0], xyz[:, 1], np.array(faces))
    info = {"points": len(xyz), "faces": len(faces),
            "area2d": float(sdef.get("area2DSurf")), "area3d": float(sdef.get("area3DSurf"))}
    return tri, xyz, info


def main():
    RES.mkdir(exist_ok=True)
    IMG.mkdir(exist_ok=True)
    root = ET.parse(XML).getroot()
    t_pl, p_pl, i_pl = read_surface(root, "Planum")
    t_dgm, p_dgm, i_dgm = read_surface(root, "DGM_Bestand")
    f_pl = mtri.LinearTriInterpolator(t_pl, p_pl[:, 2])
    f_dgm = mtri.LinearTriInterpolator(t_dgm, p_dgm[:, 2])

    # Raster ueber die Planumsflaeche: Differenz Planum - Gelaende (wie Volume Surface)
    x = np.arange(p_pl[:, 0].min(), p_pl[:, 0].max() + CELL, CELL) + CELL / 2
    y = np.arange(p_pl[:, 1].min(), p_pl[:, 1].max() + CELL, CELL) + CELL / 2
    X, Y = np.meshgrid(x, y)
    zp = f_pl(X, Y)
    zg = f_dgm(X, Y)
    inside = ~np.ma.getmaskarray(zp)
    dz = np.ma.filled(zp - zg, np.nan)
    dz[~inside] = np.nan
    d = np.nan_to_num(dz)
    cut = float(np.clip(-d, 0, None).sum() * CELL ** 2)
    fill = float(np.clip(d, 0, None).sum() * CELL ** 2)
    a_cut = float((d < 0).sum() * CELL ** 2)
    a_fill = float((d > 0).sum() * CELL ** 2)
    flat = inside & (np.abs(np.ma.filled(zp, 0) - PLANUM) < 0.001)
    gel = np.ma.filled(zg, np.nan)[flat]

    kpi = [
        ("DGM Punkte / Dreiecke", f"{i_dgm['points']} / {i_dgm['faces']}"),
        ("Planum Punkte / Dreiecke", f"{i_pl['points']} / {i_pl['faces']}"),
        ("Planum Hoehe (m)", f"{PLANUM:.2f}"),
        ("Planum Flaeche eben (m2)", "2400 (60 x 40 m)"),
        ("Flaeche mit Boeschungen 2D / 3D (m2)", f"{i_pl['area2d']:.1f} / {i_pl['area3d']:.1f}"),
        ("Gelaende unter dem Planum min / max (m)", f"{np.nanmin(gel):.2f} / {np.nanmax(gel):.2f}"),
        ("Abtrag Python (m3)", round(cut, 1)),
        ("Auftrag Python (m3)", round(fill, 1)),
        ("Netto Python (m3)", f"{fill - cut:.1f} Auftrag"),
        ("Flaeche Abtrag / Auftrag (m2)", f"{a_cut:.0f} / {a_fill:.0f}"),
        ("Abtrag / Auftrag Civil 3D (m3)", f"{CIVIL3D['cut']} / {CIVIL3D['fill']}"),
        ("Abweichung Abtrag / Auftrag (%)",
         f"{(cut - CIVIL3D['cut']) / CIVIL3D['cut'] * 100:.2f} / "
         f"{(fill - CIVIL3D['fill']) / CIVIL3D['fill'] * 100:.2f}"),
        ("Massenbilanz Auftrag / Abtrag (%)", round(fill / cut * 100, 1)),
    ]
    kp = pd.DataFrame(kpi, columns=["Kennzahl", "Wert"])
    kp.to_csv(RES / "kennzahlen.csv", index=False, sep=";")

    # Schnitte durch die Mitte (West-Ost und Sued-Nord)
    s = np.arange(-40, 40.01, 0.5)
    rows, sections = [], {}
    for name, xs, ys in (("West-Ost", CX + s, np.full_like(s, CY)),
                         ("Sued-Nord", np.full_like(s, CX), CY + s)):
        g = np.ma.filled(f_dgm(xs, ys), np.nan)
        p = np.ma.filled(f_pl(xs, ys), np.nan)
        sections[name] = (g, p)
        for a, gz, pz in zip(s, g, p):
            if a % 5 == 0:
                rows.append({"Schnitt": name, "Abstand_m": a, "Gelaende_m": round(gz, 3),
                             "Planum_m": None if np.isnan(pz) else round(pz, 3),
                             "Differenz_m": None if np.isnan(pz) else round(pz - gz, 3)})
    sch = pd.DataFrame(rows)
    sch.to_csv(RES / "schnitte.csv", index=False, sep=";", decimal=",")
    with pd.ExcelWriter(RES / "civil3d_volumenflaeche.xlsx") as xw:
        kp.to_excel(xw, sheet_name="Kennzahlen", index=False)
        sch.to_excel(xw, sheet_name="Schnitte", index=False)

    # Grafik 1: Auftrag/Abtrag-Karte (gleiche Klassen wie in Civil 3D)
    bounds = np.arange(-2.5, 2.51, 0.5)
    cols = ["#ff0000", "#cc0000", "#990000", "#660000", "#330000",
            "#66ff33", "#33bb22", "#227711", "#114408", "#082204"]
    fig, ax = plt.subplots(figsize=(10, 6.4))
    im = ax.pcolormesh(X - CX, Y - CY, dz, cmap=ListedColormap(cols),
                       norm=BoundaryNorm(bounds, len(cols)), shading="auto")
    ax.plot([-30, 30, 30, -30, -30], [-20, -20, 20, 20, -20], color="#1f3864", lw=1.5,
            label=f"Planum 60 × 40 m, {PLANUM:.2f} m")
    ax.set_aspect("equal")
    ax.set_xlabel(f"Ost − {CX:.0f} (m)")
    ax.set_ylabel(f"Nord − {CY:.0f} (m)")
    de = lambda v: f"{v:,.0f}".replace(",", ".")  # noqa: E731
    ax.set_title(f"Planum − Gelände aus LandXML: Abtrag {de(cut)} m³, Auftrag {de(fill)} m³")
    ax.legend(loc="upper right")
    fig.colorbar(im, ax=ax, label="Differenz (m): − Abtrag / + Auftrag", ticks=bounds)
    fig.tight_layout()
    fig.savefig(IMG / "03_Auftrag_Abtrag_LandXML.png", dpi=150)
    plt.close(fig)

    # Grafik 2: zwei Schnitte
    fig, axs = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True)
    for a, (name, (g, p)) in zip(axs, sections.items()):
        ok = ~np.isnan(p)
        a.fill_between(s, p, g, where=ok & (g > p), color="#c0392b", alpha=.3, label="Abtrag (cut)")
        a.fill_between(s, p, g, where=ok & (p > g), color="#27ae60", alpha=.3, label="Auftrag (fill)")
        a.plot(s, g, color="#8b5a2b", lw=1.8, label="Gelaende DGM_Bestand")
        a.plot(s, p, color="#1f3864", lw=2.2, label="Planum (Grading)")
        a.set_title(f"Schnitt {name} durch die Mitte (Böschung 1:2, Überhöhung 2-fach)", fontsize=10)
        a.set_ylabel("Hoehe (m)")
        a.set_aspect(2, adjustable="datalim")
        a.grid(alpha=.3)
        a.legend(loc="lower left", fontsize=8)
    axs[1].set_xlabel("Abstand zur Mitte (m)")
    fig.tight_layout()
    fig.savefig(IMG / "04_Schnitte_LandXML.png", dpi=150)
    plt.close(fig)
    print(kp.to_string(index=False))


if __name__ == "__main__":
    main()
