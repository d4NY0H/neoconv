# Changelog

Alle wesentlichen Änderungen zwischen Releases sind hier dokumentiert.

## [1.1.0] — 2026-05-12

### Neu

- **`.neo`-Metadaten bearbeiten (ohne Repack):** Neuer CLI-Befehl `neoconv edit` — ein oder mehrere Header-Felder (`--name`, `--manufacturer`, `--year`, `--genre`, `--ngh`, `--screenshot`) anpassen; optional `--out` für eine Kopie, sonst wird die Eingabedatei atomar überschrieben.
- **GUI:** Tab **„Edit (.neo)“** (zwischen Extract und Info): Eingabe-`.neo`, optionale Ausgabe-`.neo`, Metadaten wie im Pack-Tab; Felder werden nach kurzer Verzögerung aus dem Header (nur die ersten 4 KiB) geladen; **„Write metadata“** schreibt alle Felder in den Header, ROM-Bereiche bleiben unverändert.
- **Kern:** `parse_neo_header_metadata()`, `replace_neo_metadata()`, `write_bytes_atomic()` für die obigen Workflows.

### Geändert

- **GUI:** Tab-Reihenfolge **Pack → Extract → Edit → Info** (Pack steht vorne).
- **Info / `format_info`:** **Screenshot #** wird angezeigt; **NGH** nur noch dezimal (kein Hex-Suffix mehr).
- **GUI Pack:** Parser-Warnungen erscheinen im Tab-Log (nicht auf stderr), doppelte Warnungen zwischen Auto-Swap-Probe und Pack-Lauf werden zusammengefasst; Fortschrittsbalken durch einen kompakten **Busy-Spinner** ersetzt.
- **GUI:** Keine dauerhafte Speicherung von Tab-Formularwerten mehr in Config-Dateien; zugehörige Legacy-Hilfen und „Reset all tabs“ / per-Tab-Defaults entfernt bzw. vereinfacht.

### Entfernt

- **Verify (Roundtrip):** Tab in der GUI und Subcommand `neoconv verify` in der CLI entfernt (kein Mehrwert im Alltag). Die interne Funktion `verify_roundtrip` bleibt in `core` für Unit-Tests erhalten.

---

## [1.0.5]

Siehe Git-Tag `1.0.5` (u. a. S-ROM-Synthese für MAME-Sets ohne `s1`, GUI-Layout-Anpassungen, Tests).

[1.1.0]: https://github.com/d4NY0H/neoconv/compare/1.0.5...1.1.0
[1.0.5]: https://github.com/d4NY0H/neoconv/releases/tag/1.0.5
