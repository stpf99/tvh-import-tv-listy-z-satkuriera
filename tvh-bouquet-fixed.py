#!/usr/bin/env python3
"""
TVHeadend Bouquet Manager - FINALNA WERSJA DLA STRON BEZ KATEGORII
- Kategorie: TYLKO przez colspan (jak w oryginale)
- Jeśli colspan nie ma → WSZYSTKO do "Bez kategorii"
- Czyste nazwy (bez DVB, H, 27500)
- Brak duplikatów (globalna deduplikacja)
- Ciągła numeracja 1, 2, 3...
"""

import sys
import requests
import re
from bs4 import BeautifulSoup
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QProgressBar, QGroupBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QMessageBox, QCheckBox, QSpinBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont
from difflib import SequenceMatcher
import json


class TVHeadendAPI:
    def __init__(self, host, port, username="", password=""):
        self.base_url = f"http://{host}:{port}"
        self.auth = (username, password) if username else None
        
    def get_services(self):
        try:
            all_services = []
            start = 0
            limit = 5000
            url = f"{self.base_url}/api/mpegts/service/grid"
            while True:
                params = {'start': start, 'limit': limit}
                response = requests.get(url, params=params, auth=self.auth, timeout=10)
                response.raise_for_status()
                data = response.json()
                entries = data.get('entries', [])
                total = data.get('total', 0)
                all_services.extend(entries)
                if len(all_services) >= total or len(entries) == 0:
                    break
                start += limit
            return all_services
        except Exception as e:
            raise Exception(f"Błąd pobierania usług: {str(e)}")
    
    def get_channels(self):
        try:
            url = f"{self.base_url}/api/channel/grid"
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json().get('entries', [])
        except Exception as e:
            raise Exception(f"Błąd pobierania kanałów: {str(e)}")
    
    def get_tags(self):
        try:
            url = f"{self.base_url}/api/channeltag/grid"
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json().get('entries', [])
        except Exception as e:
            raise Exception(f"Błąd pobierania tagów: {str(e)}")
    
    def create_tag(self, name, comment="", index=None):
        try:
            url = f"{self.base_url}/api/channeltag/create"
            conf = {'name': name, 'comment': comment, 'enabled': True}
            if index is not None: conf['index'] = index
            data = {'conf': json.dumps(conf)}
            response = requests.post(url, data=data, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Błąd tworzenia tagu: {str(e)}")
    
    def update_channel(self, channel_uuid, tags=None, number=None, name=None):
        try:
            url = f"{self.base_url}/api/channel/save"
            updates = {'uuid': channel_uuid}
            if tags is not None: updates['tags'] = tags
            if number is not None: updates['number'] = number
            if name is not None: updates['name'] = name
            data = {'node': json.dumps(updates)}
            response = requests.post(url, data=data, auth=self.auth, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            raise Exception(f"Błąd aktualizacji kanału: {str(e)}")
    
    def create_channel_from_service(self, service_uuid, name, tags=None, number=None):
        try:
            url = f"{self.base_url}/api/channel/create"
            conf = {'services': [service_uuid], 'name': name, 'enabled': True}
            if tags: conf['tags'] = tags
            if number: conf['number'] = number
            data = {'conf': json.dumps(conf)}
            response = requests.post(url, data=data, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Błąd tworzenia kanału: {str(e)}")


class BouquetParser:
    """Klasa do parsowania list kanałów ze stron WWW"""
    
    @staticmethod
    def normalize_channel_name(name):
        """
        Normalizuje nazwę kanału do porównywania:
        - usuwa jakość (HD, SD, UHD, 4K)
        - usuwa parametry techniczne
        - normalizuje białe znaki
        """
        if not name:
            return ""
        
        normalized = name.lower()
        
        # Usuń jakość obrazu
        normalized = re.sub(r'\b(hd|sd|uhd|4k|ud)\b', '', normalized, flags=re.IGNORECASE)
        
        # Usuń parametry techniczne DVB/DB
        normalized = re.sub(r'\b(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\b', '', normalized, flags=re.IGNORECASE)
        
        # Usuń "D D" i pojedyncze "D"
        normalized = re.sub(r'\s+d\s+d\s*$', '', normalized)
        normalized = re.sub(r'\s+d\s*$', '', normalized)
        
        # Normalizuj białe znaki
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # Usuń znaki specjalne oprócz + i -
        normalized = re.sub(r'[^\w\s\+\-]', '', normalized)
        
        return normalized
    
    @staticmethod
    def clean_channel_name(name):
        """
        Czyści nazwę kanału do zapisania (usuwa parametry techniczne, zostawia jakość)
        """
        if not name:
            return ""
        
        cleaned = name
        
        # Usuń parametry techniczne DVB/DB
        cleaned = re.sub(r'\s*(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\s*', '', cleaned, flags=re.IGNORECASE)
        
        # Usuń "D D" na końcu
        cleaned = re.sub(r'\s+D\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s+D\s*$', '', cleaned)
        
        # Usuń pojedyncze "-" na końcu
        cleaned = re.sub(r'\s*-\s*$', '', cleaned)
        
        # Normalizuj białe znaki
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Upewnij się, że HD/SD/UHD/4K jest na końcu (jeśli występuje)
        quality_match = re.search(r'\b(HD|SD|UHD|4K)\b', cleaned, flags=re.IGNORECASE)
        if quality_match:
            quality = quality_match.group(1).upper()
            cleaned = re.sub(r'\s*\b(HD|SD|UHD|4K)\b\s*', ' ', cleaned, flags=re.IGNORECASE).strip()
            cleaned = f"{cleaned} {quality}"
        
        return cleaned
    
    @staticmethod
    def parse_satkurier(url):
        """Parsuje listę kanałów z satkurier.pl"""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            bouquets = {}
            current_category = "Bez kategorii"
            channel_number = 1
            
            tables = soup.find_all('table')
            
            for table in tables:
                rows = table.find_all('tr')
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    
                    if not cells:
                        continue
                    
                    if len(cells) == 1 and cells[0].get('colspan'):
                        header_text = cells[0].get_text(strip=True)
                        if header_text and len(header_text) > 2:
                            current_category = header_text
                            if current_category not in bouquets:
                                bouquets[current_category] = []
                        continue
                    
                    if len(cells) >= 1:
                        full_text = ' '.join(cell.get_text(strip=True) for cell in cells)
                        
                        if not full_text or full_text.isdigit():
                            continue
                        
                        channel_info = BouquetParser.parse_channel_info(full_text)
                        
                        if channel_info and channel_info['name']:
                            if current_category not in bouquets:
                                bouquets[current_category] = []
                            channel_info['number'] = channel_number
                            channel_info['category'] = current_category
                            bouquets[current_category].append(channel_info)
                            channel_number += 1
            
            return bouquets
        except Exception as e:
            raise Exception(f"Błąd parsowania strony: {str(e)}")
    
    @staticmethod
    def parse_channel_info(text):
        """Parsuje informacje o kanale z tekstu"""
        text = re.sub(r'^\d+\.?\s*', '', text)
        
        if not text or len(text) < 2:
            return None
        
        info = {
            'name': '',
            'full_text': text,
            'quality': '',
            'frequency': '',
            'polarization': '',
            'symbol_rate': '',
            'fec': '',
            'modulation': ''
        }
        
        # Wykryj parametry techniczne
        freq_match = re.search(r'(\d{1,2}[.,]\d{3})', text)
        if freq_match:
            info['frequency'] = freq_match.group(1)
        
        pol_match = re.search(r'\b([VHLR])\b', text)
        if pol_match:
            info['polarization'] = pol_match.group(1)
        
        sr_match = re.search(r'\b(\d{5})\b', text)
        if sr_match:
            info['symbol_rate'] = sr_match.group(1)
        
        fec_match = re.search(r'(\d/\d)', text)
        if fec_match:
            info['fec'] = fec_match.group(1)
        
        mod_match = re.search(r'(DVB-[ST]\d?(?:/\w+)?|DB-S\d?/\w+)', text, flags=re.IGNORECASE)
        if mod_match:
            info['modulation'] = mod_match.group(1)
        
        quality_match = re.search(r'\b(HD|SD|UHD|4K|UD)\b', text, flags=re.IGNORECASE)
        if quality_match:
            info['quality'] = quality_match.group(1).upper()
        
        # Wyczyść nazwę kanału
        info['name'] = BouquetParser.clean_channel_name(text)
        
        return info
    
    @staticmethod
    def similarity(a, b):
        """Oblicza podobieństwo dwóch stringów z normalizacją"""
        norm_a = BouquetParser.normalize_channel_name(a)
        norm_b = BouquetParser.normalize_channel_name(b)
        
        if not norm_a or not norm_b:
            return 0.0
        
        return SequenceMatcher(None, norm_a, norm_b).ratio()


class ImportWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, api, bouquets, services, threshold=0.05, create_tags=True):
        super().__init__()
        self.api = api
        self.bouquets = bouquets
        self.services = services
        self.threshold = threshold
        self.create_tags = create_tags
        
    def run(self):
        try:
            # === DEDUPLIKACJA GLOBALNA + CIĄGŁA NUMERACJA ===
            unique_channels = {}
            global_number = 1
            for cat, chans in self.bouquets.items():
                for ch in chans:
                    norm = BouquetParser.normalize_channel_name(ch['name'])
                    if norm and norm not in unique_channels:
                        ch2 = ch.copy()
                        ch2['number'] = global_number
                        ch2['category'] = cat
                        unique_channels[norm] = ch2
                        global_number += 1

            new_bouquets = {}
            for norm, ch in unique_channels.items():
                cat = ch['category']
                new_bouquets.setdefault(cat, []).append(ch)
            self.bouquets = new_bouquets

            total_channels = sum(len(v) for v in self.bouquets.values())
            processed = matched = created_channels = updated_channels = 0

            self.progress.emit(0, "Pobieranie tagów...")
            existing_tags = {tag['name']: tag['uuid'] for tag in self.api.get_tags()}

            services_map = {}
            for s in self.services:
                name = s.get('svcname', '')
                if name:
                    norm = BouquetParser.normalize_channel_name(name)
                    services_map[norm] = s

            self.progress.emit(5, f"Usług: {len(services_map)}")
            self.progress.emit(10, "Pobieranie kanałów...")
            existing_channels = self.api.get_channels()
            channels_by_service = {}
            for ch in existing_channels:
                for svc_uuid in ch.get('services', []):
                    channels_by_service[svc_uuid] = ch
            self.progress.emit(15, f"Kanałów: {len(existing_channels)}")

            processed_services = set()
            tag_index = 0

            for category, channels in self.bouquets.items():
                self.progress.emit(15 + int((processed / total_channels) * 70), f"Kategoria: {category}")
                tag_uuid = None
                if self.create_tags:
                    if category in existing_tags:
                        tag_uuid = existing_tags[category]
                    else:
                        result = self.api.create_tag(category, "Import z listy", tag_index)
                        tag_uuid = result.get('uuid')
                        existing_tags[category] = tag_uuid
                        tag_index += 1

                for ch_info in channels:
                    ch_name = ch_info['name']
                    ch_num = ch_info['number']
                    norm_search = BouquetParser.normalize_channel_name(ch_name)

                    best_match = None
                    best_score = 0
                    variants = [norm_search, norm_search.replace(' ', ''), norm_search.replace('+', ' plus'), norm_search.replace('+', '')]

                    for svc_norm, service in services_map.items():
                        if svc_norm in processed_services: continue
                        for v in variants:
                            score = SequenceMatcher(None, v, svc_norm).ratio()
                            if score > best_score:
                                best_score = score
                                best_match = service

                    if best_match and best_score >= self.threshold:
                        svc_uuid = best_match['uuid']
                        processed_services.add(svc_uuid)
                        if svc_uuid in channels_by_service:
                            ch = channels_by_service[svc_uuid]
                            tags = ch.get('tags', [])
                            if tag_uuid and tag_uuid not in tags:
                                tags.append(tag_uuid)
                            self.api.update_channel(ch['uuid'], tags, ch_num, ch_name)
                            updated_channels += 1
                        else:
                            tags = [tag_uuid] if tag_uuid else []
                            self.api.create_channel_from_service(svc_uuid, ch_name, tags, ch_num)
                            created_channels += 1
                        matched += 1
                    processed += 1

            self.progress.emit(100, "Zakończono!")
            summary = f"Import zakończony!\nPrzetworzono: {processed}\nDopasowano: {matched}\nUtworzono: {created_channels}\nZaktualizowano: {updated_channels}\nNie dopasowano: {processed-matched}"
            self.finished.emit(True, summary)

        except Exception as e:
            self.finished.emit(False, f"Błąd: {str(e)}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = None
        self.services = []
        self.bouquets = {}
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("TVHeadend Bouquet Manager")
        self.setGeometry(100, 100, 900, 700)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        tvh_g = QGroupBox("TVHeadend")
        tvh_l = QVBoxLayout()
        conn_l = QHBoxLayout()
        conn_l.addWidget(QLabel("Host:")); self.host_input = QLineEdit("localhost"); conn_l.addWidget(self.host_input)
        conn_l.addWidget(QLabel("Port:")); self.port_input = QLineEdit("9981"); self.port_input.setMaximumWidth(80); conn_l.addWidget(self.port_input)
        conn_l.addWidget(QLabel("Login:")); self.user_input = QLineEdit(); self.user_input.setMaximumWidth(120); conn_l.addWidget(self.user_input)
        conn_l.addWidget(QLabel("Hasło:")); self.pass_input = QLineEdit(); self.pass_input.setEchoMode(QLineEdit.EchoMode.Password); self.pass_input.setMaximumWidth(120); conn_l.addWidget(self.pass_input)
        self.connect_btn = QPushButton("Połącz"); self.connect_btn.clicked.connect(self.connect_tvh); conn_l.addWidget(self.connect_btn)
        tvh_l.addLayout(conn_l)
        self.services_label = QLabel("Status: Niepołączony"); tvh_l.addWidget(self.services_label)
        tvh_g.setLayout(tvh_l); layout.addWidget(tvh_g)

        src_g = QGroupBox("Lista kanałów")
        src_l = QVBoxLayout()
        url_l = QHBoxLayout()
        url_l.addWidget(QLabel("URL:")); self.url_input = QLineEdit(); self.url_input.setPlaceholderText("https://satkurier.pl/news/234203/lista-kanalow-polsat-box.html"); url_l.addWidget(self.url_input)
        self.parse_btn = QPushButton("Pobierz"); self.parse_btn.clicked.connect(self.parse_bouquet); self.parse_btn.setEnabled(False); url_l.addWidget(self.parse_btn)
        src_l.addLayout(url_l); src_g.setLayout(src_l); layout.addWidget(src_g)

        tabs = QTabWidget()
        prev_tab = QWidget(); prev_l = QVBoxLayout(prev_tab); self.preview_text = QTextEdit(); self.preview_text.setReadOnly(True); prev_l.addWidget(self.preview_text); tabs.addTab(prev_tab, "Podgląd")
        svc_tab = QWidget(); svc_l = QVBoxLayout(svc_tab); self.services_table = QTableWidget(); self.services_table.setColumnCount(3); self.services_table.setHorizontalHeaderLabels(["Usługa", "Typ", "UUID"]); self.services_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch); svc_l.addWidget(self.services_table); tabs.addTab(svc_tab, "Usługi")
        layout.addWidget(tabs)

        imp_g = QGroupBox("Import")
        imp_l = QVBoxLayout()
        opt_l = QHBoxLayout()
        opt_l.addWidget(QLabel("Próg:")); self.threshold_spin = QSpinBox(); self.threshold_spin.setRange(5,100); self.threshold_spin.setValue(5); self.threshold_spin.setSuffix("%"); opt_l.addWidget(self.threshold_spin)
        self.create_tags_check = QCheckBox("Twórz tagi"); self.create_tags_check.setChecked(True); opt_l.addWidget(self.create_tags_check); opt_l.addStretch()
        imp_l.addLayout(opt_l)
        self.import_btn = QPushButton("Importuj do TVHeadend"); self.import_btn.clicked.connect(self.start_import); self.import_btn.setEnabled(False); imp_l.addWidget(self.import_btn)
        self.progress_bar = QProgressBar(); imp_l.addWidget(self.progress_bar)
        self.status_text = QTextEdit(); self.status_text.setMaximumHeight(100); self.status_text.setReadOnly(True); imp_l.addWidget(self.status_text)
        imp_g.setLayout(imp_l); layout.addWidget(imp_g)

    def connect_tvh(self):
        try:
            self.api = TVHeadendAPI(self.host_input.text(), self.port_input.text(), self.user_input.text(), self.pass_input.text())
            self.services = self.api.get_services()
            self.services_label.setText(f"Połączono: {len(self.services)} usług")
            self.parse_btn.setEnabled(True)
            self.services_table.setRowCount(len(self.services))
            for i, s in enumerate(self.services):
                self.services_table.setItem(i, 0, QTableWidgetItem(s.get('svcname','')))
                self.services_table.setItem(i, 1, QTableWidgetItem(s.get('svctype','')))
                self.services_table.setItem(i, 2, QTableWidgetItem(s.get('uuid','')))
            self.status_text.append("Połączono")
        except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

    def parse_bouquet(self):
        try:
            url = self.url_input.text()
            if not url: raise ValueError("Podaj URL")
            self.bouquets = BouquetParser.parse_satkurier(url)
            total = sum(len(v) for v in self.bouquets.values())
            preview = ""
            for cat, chs in self.bouquets.items():
                preview += f"\n{'='*60}\n{cat} ({len(chs)})\n{'='*60}\n"
                for ch in chs[:10]:
                    preview += f"{ch['number']:3d}. {ch['name']}\n"
                if len(chs)>10: preview += f"... i {len(chs)-10} więcej\n"
            self.preview_text.setText(preview)
            self.status_text.append(f"Pobrano: {len(self.bouquets)} kat., {total} kanałów")
            if self.services: self.import_btn.setEnabled(True)
        except Exception as e: QMessageBox.critical(self, "Błąd", str(e))

    def start_import(self):
        if not self.api or not self.bouquets: return
        self.import_btn.setEnabled(False)
        self.worker = ImportWorker(self.api, self.bouquets, self.services, self.threshold_spin.value()/100.0, self.create_tags_check.isChecked())
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.import_finished)
        self.worker.start()

    def update_progress(self, v, m): self.progress_bar.setValue(v); self.status_text.append(m)
    def import_finished(self, ok, msg): self.import_btn.setEnabled(True); (QMessageBox.information if ok else QMessageBox.critical)(self, "Sukces" if ok else "Błąd", msg)


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("", 9))
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
