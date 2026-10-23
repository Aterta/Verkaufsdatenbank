from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
import mysql.connector
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="Werkstatt Verkauf API")

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/app")
def handy_app():
    return FileResponse("static/index.html")

def get_db():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME")
    )

class Position(BaseModel):
    artikelnummer: str
    preis: float
    werkstatt_id: int          # welche Werkstatt dieses Produkt verkauft
    menge: int = 1

@app.get("/")
def root():
    return {"message": "Werkstatt Verkauf API läuft"}

@app.post("/beleg")
def beleg_starten():
    """Neuen Beleg am gemeinsamen Stand starten (ohne Werkstatt)"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("INSERT INTO belege () VALUES ()")
        # Falls leeres INSERT Probleme macht:
        # cursor.execute("INSERT INTO belege (gesamtpreis) VALUES (0)")

        conn.commit()
        beleg_id = cursor.lastrowid

        cursor.close()
        conn.close()

        return {"message": "Beleg gestartet", "beleg_id": beleg_id}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/beleg/{beleg_id}/position")
def position_hinzufuegen(beleg_id: int, daten: Position):
    """Artikel zu einem Beleg hinzufügen – Werkstatt kommt pro Position"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT id, abgeschlossen FROM belege WHERE id = %s",
            (beleg_id,)
        )
        beleg = cursor.fetchone()
        if not beleg:
            raise HTTPException(status_code=404, detail="Beleg nicht gefunden")
        if beleg["abgeschlossen"]:
            raise HTTPException(status_code=400, detail="Beleg ist bereits abgeschlossen")

        # Produkt bei Bedarf anlegen
        cursor.execute(
            "SELECT artikelnummer FROM produkte WHERE artikelnummer = %s",
            (daten.artikelnummer,)
        )
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO produkte (artikelnummer, preis) VALUES (%s, %s)",
                (daten.artikelnummer, daten.preis)
            )

        # Position mit Werkstatt speichern
        cursor.execute(
            """
            INSERT INTO verkaeufe (artikelnummer, werkstatt_id, menge, preis_zum_zeitpunkt, beleg_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (daten.artikelnummer, daten.werkstatt_id, daten.menge, daten.preis, beleg_id)
        )

        # Gesamtpreis aktualisieren
        cursor.execute(
            """
            UPDATE belege
            SET gesamtpreis = (
                SELECT COALESCE(SUM(menge * preis_zum_zeitpunkt), 0)
                FROM verkaeufe WHERE beleg_id = %s
            )
            WHERE id = %s
            """,
            (beleg_id, beleg_id)
        )

        conn.commit()

        cursor.execute("SELECT gesamtpreis FROM belege WHERE id = %s", (beleg_id,))
        gesamt = cursor.fetchone()["gesamtpreis"]

        cursor.close()
        conn.close()

        return {
            "message": "Position hinzugefügt",
            "beleg_id": beleg_id,
            "artikelnummer": daten.artikelnummer,
            "werkstatt_id": daten.werkstatt_id,
            "gesamtpreis": float(gesamt)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/beleg/{beleg_id}")
def beleg_anzeigen(beleg_id: int):
    """Beleg mit Positionen (inkl. Werkstatt) und Gesamtpreis"""
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id, erstellt_am, gesamtpreis, abgeschlossen
            FROM belege WHERE id = %s
            """,
            (beleg_id,)
        )
        beleg = cursor.fetchone()
        if not beleg:
            raise HTTPException(status_code=404, detail="Beleg nicht gefunden")

        cursor.execute(
            """
            SELECT v.artikelnummer, v.menge, v.preis_zum_zeitpunkt,
                   (v.menge * v.preis_zum_zeitpunkt) AS summe,
                   v.werkstatt_id, w.name AS werkstatt
            FROM verkaeufe v
            JOIN werkstaetten w ON v.werkstatt_id = w.id
            WHERE v.beleg_id = %s
            ORDER BY v.id
            """,
            (beleg_id,)
        )
        positionen = cursor.fetchall()

        cursor.close()
        conn.close()

        return {"beleg": beleg, "positionen": positionen}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/beleg/{beleg_id}/abschluss")
def beleg_abschliessen(beleg_id: int):
    try:
        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "UPDATE belege SET abgeschlossen = TRUE WHERE id = %s AND abgeschlossen = FALSE",
            (beleg_id,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=400, detail="Beleg nicht gefunden oder bereits abgeschlossen")

        conn.commit()

        cursor.execute("SELECT gesamtpreis FROM belege WHERE id = %s", (beleg_id,))
        gesamt = cursor.fetchone()["gesamtpreis"]

        cursor.close()
        conn.close()

        return {
            "message": "Beleg abgeschlossen",
            "beleg_id": beleg_id,
            "gesamtpreis": float(gesamt)
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))