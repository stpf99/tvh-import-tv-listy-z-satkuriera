#!/usr/bin/env python3
"""
TVHeadend Bouquet Manager - Wersja z mapowaniem typu klucz-wartość
Główne zmiany:
- Mapowanie: tylko litery (bez cyfr, spacji, znaków specjalnych)
- Przykład: "Polsat Sport HD" → klucz: "polsatsport" → "Polsat Sport"
- Wybór źródła nazw: serwer TVHeadend lub lista zdalna
- Usunięcie procentowego dopasowania - tylko exact match na kluczu
"""

import sys
import requests
import re
from bs4 import BeautifulSoup
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                             QTextEdit, QProgressBar, QGroupBox, QTabWidget,
                             QTableWidget, QTableWidgetItem, QHeaderView,
                             QMessageBox, QCheckBox)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont
import json


class TVHeadendAPI:
    """Klasa do komunikacji z TVHeadend API"""
    
    def __init__(self, host, port, username="", password=""):
        self.base_url = f"http://{host}:{port}"
        self.auth = (username, password) if username else None
        
    def get_services(self):
        """Pobiera WSZYSTKIE usługi (kanały) z TVHeadend"""
        try:
            all_services = []
            start = 0
            limit = 500
            
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
        """Pobiera wszystkie kanały z TVHeadend"""
        try:
            url = f"{self.base_url}/api/channel/grid"
            params = {'start': 0, 'limit': 999999}
            response = requests.get(url, params=params, auth=self.auth, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('entries', [])
        except Exception as e:
            raise Exception(f"Błąd pobierania kanałów: {str(e)}")
    
    def get_tags(self):
        """Pobiera listę tagów z TVHeadend"""
        try:
            url = f"{self.base_url}/api/channeltag/grid"
            response = requests.get(url, auth=self.auth, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('entries', [])
        except Exception as e:
            raise Exception(f"Błąd pobierania tagów: {str(e)}")
    
    def create_tag(self, name, comment="", index=None):
        """Tworzy nowy tag"""
        try:
            url = f"{self.base_url}/api/channeltag/create"
            conf = {'name': name, 'comment': comment, 'enabled': True}
            if index is not None:
                conf['index'] = index
            
            data = {'conf': json.dumps(conf)}
            response = requests.post(url, data=data, auth=self.auth, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            raise Exception(f"Błąd tworzenia tagu: {str(e)}")
    
    def update_channel(self, channel_uuid, tags=None, number=None, name=None):
        """Aktualizuje kanał"""
        try:
            url = f"{self.base_url}/api/channel/save"
            updates = {'uuid': channel_uuid}
            if tags is not None:
                updates['tags'] = tags
            if number is not None:
                updates['number'] = number
            if name is not None:
                updates['name'] = name
            
            data = {'node': json.dumps(updates)}
            response = requests.post(url, data=data, auth=self.auth, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            raise Exception(f"Błąd aktualizacji kanału: {str(e)}")
    
    def create_channel_from_service(self, service_uuid, name, tags=None, number=None):
        """Tworzy kanał z usługi"""
        try:
            url = f"{self.base_url}/api/channel/create"
            conf = {
                'services': [service_uuid],
                'name': name,
                'enabled': True
            }
            if tags:
                conf['tags'] = tags
            if number:
                conf['number'] = number
            
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
        Normalizuje nazwę kanału do klucza mapowania:
        - tylko litery (bez cyfr, znaków specjalnych, spacji)
        - małe litery
        - usuwa wszystko oprócz liter (bez HD, SD, liczb, symboli)
        """
        if not name:
            return ""
        
        # Konwersja na małe litery
        normalized = name.lower()
        
        # Usuń wszystko oprócz liter (a-z)
        normalized = re.sub(r'[^a-z]', '', normalized)
        
        return normalized
    
    @staticmethod
    def clean_channel_name(name):
        """
        Czyści nazwę kanału do zapisania (usuwa parametry techniczne i gatunki)
        """
        if not name:
            return ""
        
        cleaned = name
        
        # Lista słów kluczowych gatunków do usunięcia (czesto znajdują się w kolumnie Nazwa lub na jej końcu)
        genres = r'\b(muzyczny|informacyjny|uniwersalny|filmowy|sportowy|religijny|dokumentalny|rozrywkowy|dla dzieci|telezakupowy|prawniczy|kulinarny|motoryzacyjny|erotyczny|turystyczny|lifestyle)\b'
        cleaned = re.sub(genres, '', cleaned, flags=re.IGNORECASE)

        # Usuń parametry techniczne DVB/DB
        cleaned = re.sub(r'\s*(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\s*', '', cleaned, flags=re.IGNORECASE)
        
        # Usuń jakość HD/SD/UHD/4K
        cleaned = re.sub(r'\s*\b(HD|SD|UHD|4K|UD)\b\s*', ' ', cleaned, flags=re.IGNORECASE)
        
        # Usuń parametry satelitarne (częstotliwość, polaryzacja, symbol rate, FEC, modulacja)
        cleaned = re.sub(r'\d{1,2}[.,]\d{3}', '', cleaned)  # częstotliwość
        cleaned = re.sub(r'\b[VHLR]\b', '', cleaned)  # polaryzacja
        cleaned = re.sub(r'\b\d{5}\b', '', cleaned)  # symbol rate
        cleaned = re.sub(r'\d/\d', '', cleaned)  # FEC
        cleaned = re.sub(r'\bs\d/\w+\b', '', cleaned, flags=re.IGNORECASE)  # modulacja
        
        # Usuń "D D" i pojedyncze "D"
        cleaned = re.sub(r'\s+D\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s+D\s*$', '', cleaned)
        
        # Usuń pojedyncze "-" lub "+" na końcu
        cleaned = re.sub(r'\s*[-+]\s*$', '', cleaned)
        
        # Normalizuj białe znaki
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        return cleaned
    
    @staticmethod
    def create_mapping_key(name):
        """
        Tworzy klucz mapowania - tylko litery, bez cyfr i znaków specjalnych
        Przykłady:
        "Polsat Sport HD" → "polsatsport"
        "Canal+ Sport" → "canalsport"
        "TVN 24" → "tvn"
        """
        return BouquetParser.normalize_channel_name(name)
    
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
                
                # Znajdź indeks kolumny "Nazwa" w nagłówku tabeli
                name_col_index = -1
                
                for row in rows:
                    cells = row.find_all(['td', 'th'])
                    if not cells:
                        continue
                    
                    # Sprawdź czy to wiersz nagłówka (zawiera słowa kluczowe)
                    header_texts = [cell.get_text(strip=True) for cell in cells]
                    header_str = ' '.join(header_texts).lower()
                    
                    if "nazwa" in header_str and ("tp" in header_str or "freq" in header_str):
                        # To jest nagłówek tabeli, znajdź kolumnę "Nazwa"
                        for i, text in enumerate(header_texts):
                            if "nazwa" in text.lower():
                                name_col_index = i
                                break
                        continue # Pomiń przetwarzanie nagłówka jako kanału

                    # Sprawdź czy to nagłówek kategorii (często ma colspan)
                    if len(cells) == 1 and cells[0].get('colspan'):
                        header_text = cells[0].get_text(strip=True)
                        if header_text and len(header_text) > 2:
                            current_category = header_text
                            if current_category not in bouquets:
                                bouquets[current_category] = []
                            channel_number = 1  # Reset numeracji w nowej kategorii
                        continue

                    # Przetwarzanie wiersza z kanałem
                    if len(cells) >= 1:
                        # Jeśli wykryto kolumnę Nazwa, użyj jej, w przeciwnym razie użyj całego tekstu (fallback)
                        if name_col_index != -1 and name_col_index < len(cells):
                            full_text = cells[name_col_index].get_text(strip=True)
                        else:
                            full_text = ' '.join(cell.get_text(strip=True) for cell in cells)
                        
                        if not full_text or full_text.isdigit():
                            continue
                        
                        # Sprawdzenie czy to nie jest jakiś śmieciowy wiersz (np. same myślniki)
                        if re.match(r'^[\s\-_]+$', full_text):
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
        
        # Wykryj parametry techniczne (jeśli wciąż obecne w tekście)
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

class ImportWorker(QThread):
    """Wątek do importu bouquetów"""
    
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, api, bouquets, services, use_service_names=True, create_tags=True):
        super().__init__()
        self.api = api
        self.bouquets = bouquets
        self.services = services
        self.use_service_names = use_service_names  # True = użyj nazw z serwera, False = z listy zdalnej
        self.create_tags = create_tags
        
    def run(self):
        try:
            total_channels = sum(len(channels) for channels in self.bouquets.values())
            processed = 0
            matched = 0
            created_channels = 0
            updated_channels = 0
            
            self.progress.emit(0, "Pobieranie istniejących tagów...")
            
            existing_tags = {tag['name']: tag['uuid'] for tag in self.api.get_tags()}
            
            # Twórz mapę usług: klucz_mapowania → service
            self.progress.emit(5, "Tworzenie mapy usług...")
            services_map = {}
            for service in self.services:
                name = service.get('svcname', '')
                if name:
                    mapping_key = BouquetParser.create_mapping_key(name)
                    if mapping_key and mapping_key not in services_map:  # unikaj duplikatów
                        services_map[mapping_key] = service
            
            self.progress.emit(10, f"Mapa usług: {len(services_map)} unikalnych kluczy")
            
            # Twórz mapę kanałów z listy zdalnej: klucz_mapowania → channel_info
            self.progress.emit(12, "Tworzenie mapy kanałów ze zdalnej listy...")
            remote_map = {}
            for category, channels in self.bouquets.items():
                for ch_info in channels:
                    name = ch_info['name']
                    mapping_key = BouquetParser.create_mapping_key(name)
                    if mapping_key and mapping_key not in remote_map:
                        remote_map[mapping_key] = ch_info
            
            self.progress.emit(14, f"Mapa zdalnych kanałów: {len(remote_map)} unikalnych kluczy")
            
            self.progress.emit(15, "Pobieranie istniejących kanałów...")
            existing_channels = self.api.get_channels()
            channels_by_service = {}
            for ch in existing_channels:
                services = ch.get('services', [])
                if services:
                    for svc_uuid in services:
                        channels_by_service[svc_uuid] = ch
            
            self.progress.emit(18, f"Znaleziono {len(existing_channels)} istniejących kanałów")
            
            # Śledź przetworzone usługi
            processed_services = set()
            
            tag_index = 0
            for category, channels in self.bouquets.items():
                self.progress.emit(
                    18 + int((processed / total_channels) * 72),
                    f"Przetwarzam kategorię: {category}"
                )
                
                tag_uuid = None
                if self.create_tags:
                    if category in existing_tags:
                        tag_uuid = existing_tags[category]
                    else:
                        result = self.api.create_tag(category, f"Importowane z listy", tag_index)
                        tag_uuid = result.get('uuid')
                        existing_tags[category] = tag_uuid
                        tag_index += 1
                        self.progress.emit(
                            18 + int((processed / total_channels) * 72),
                            f"  ✓ Utworzono tag '{category}'"
                        )
                
                for channel_info in channels:
                    original_name = channel_info['name']
                    channel_number = channel_info['number']
                    
                    # Klucz mapowania
                    mapping_key = BouquetParser.create_mapping_key(original_name)
                    
                    if not mapping_key:
                        self.progress.emit(
                            18 + int((processed / total_channels) * 72),
                            f"  ✗ Pominięto (brak liter): {original_name}"
                        )
                        processed += 1
                        continue
                    
                    # Sprawdź czy istnieje dopasowanie w mapie usług
                    if mapping_key in services_map:
                        service = services_map[mapping_key]
                        service_uuid = service['uuid']
                        
                        # Pomiń jeśli już przetworzone
                        if service_uuid in processed_services:
                            self.progress.emit(
                                18 + int((processed / total_channels) * 72),
                                f"  ⊗ Pominięto (duplikat): {original_name}"
                            )
                            processed += 1
                            continue
                        
                        processed_services.add(service_uuid)
                        
                        # Wybierz nazwę do zapisu
                        if self.use_service_names:
                            # Użyj oczyszczonej nazwy z serwera TVHeadend
                            final_name = BouquetParser.clean_channel_name(service.get('svcname', ''))
                        else:
                            # Użyj oczyszczonej nazwy z listy zdalnej
                            final_name = BouquetParser.clean_channel_name(original_name)
                        
                        service_original = service.get('svcname', '')
                        
                        if service_uuid in channels_by_service:
                            # Aktualizuj istniejący kanał
                            existing_channel = channels_by_service[service_uuid]
                            tags = existing_channel.get('tags', [])
                            if tag_uuid and tag_uuid not in tags:
                                tags.append(tag_uuid)
                            
                            self.api.update_channel(
                                existing_channel['uuid'],
                                tags=tags,
                                number=channel_number,
                                name=final_name
                            )
                            updated_channels += 1
                            self.progress.emit(
                                18 + int((processed / total_channels) * 72),
                                f"  ✓ Zaktualizowano: {final_name} [{mapping_key}] (serwer: {service_original})"
                            )
                        else:
                            # Utwórz nowy kanał
                            tags = [tag_uuid] if tag_uuid else []
                            self.api.create_channel_from_service(
                                service_uuid,
                                final_name,
                                tags=tags,
                                number=channel_number
                            )
                            created_channels += 1
                            self.progress.emit(
                                18 + int((processed / total_channels) * 72),
                                f"  ✓ Utworzono: {final_name} [{mapping_key}] (serwer: {service_original})"
                            )
                        
                        matched += 1
                    else:
                        self.progress.emit(
                            18 + int((processed / total_channels) * 72),
                            f"  ✗ Nie znaleziono: {original_name} [{mapping_key}]"
                        )
                    
                    processed += 1
            
            self.progress.emit(100, "Import zakończony!")
            
            summary = (
                f"Import zakończony!\n\n"
                f"Przetworzono: {processed} kanałów\n"
                f"Dopasowano: {matched} kanałów\n"
                f"Utworzono nowych: {created_channels}\n"
                f"Zaktualizowano: {updated_channels}\n"
                f"Nie dopasowano: {processed - matched}"
            )
            self.finished.emit(True, summary)
            
        except Exception as e:
            self.finished.emit(False, f"Błąd importu: {str(e)}")


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
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        tvh_group = QGroupBox("Konfiguracja TVHeadend")
        tvh_layout = QVBoxLayout()
        
        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("Host:"))
        self.host_input = QLineEdit("localhost")
        conn_layout.addWidget(self.host_input)
        
        conn_layout.addWidget(QLabel("Port:"))
        self.port_input = QLineEdit("9981")
        self.port_input.setMaximumWidth(80)
        conn_layout.addWidget(self.port_input)
        
        conn_layout.addWidget(QLabel("Login:"))
        self.user_input = QLineEdit()
        self.user_input.setMaximumWidth(120)
        conn_layout.addWidget(self.user_input)
        
        conn_layout.addWidget(QLabel("Hasło:"))
        self.pass_input = QLineEdit()
        self.pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.pass_input.setMaximumWidth(120)
        conn_layout.addWidget(self.pass_input)
        
        self.connect_btn = QPushButton("Połącz")
        self.connect_btn.clicked.connect(self.connect_tvh)
        conn_layout.addWidget(self.connect_btn)
        
        tvh_layout.addLayout(conn_layout)
        
        self.services_label = QLabel("Status: Niepołączony")
        tvh_layout.addWidget(self.services_label)
        
        tvh_group.setLayout(tvh_layout)
        layout.addWidget(tvh_group)
        
        source_group = QGroupBox("Lista kanałów źródłowa")
        source_layout = QVBoxLayout()
        
        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("URL listy:"))
        self.url_input = QLineEdit("https://satkurier.pl/news/236485/polskie-kanaly-tv-za-darmo-z-satelity.html")
        self.url_input.setPlaceholderText("https://satkurier.pl/news/236485/polskie-kanaly-tv-za-darmo-z-satelity.html")
        url_layout.addWidget(self.url_input)
        
        self.parse_btn = QPushButton("Pobierz listę")
        self.parse_btn.clicked.connect(self.parse_bouquet)
        self.parse_btn.setEnabled(False)
        url_layout.addWidget(self.parse_btn)
        
        source_layout.addLayout(url_layout)
        source_group.setLayout(source_layout)
        layout.addWidget(source_group)
        
        tabs = QTabWidget()
        
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        
        tabs.addTab(preview_tab, "Podgląd listy")
        
        services_tab = QWidget()
        services_layout = QVBoxLayout(services_tab)
        
        self.services_table = QTableWidget()
        self.services_table.setColumnCount(3)
        self.services_table.setHorizontalHeaderLabels(["Nazwa usługi", "Typ", "UUID"])
        self.services_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        services_layout.addWidget(self.services_table)
        
        tabs.addTab(services_tab, "Usługi TVHeadend")
        
        layout.addWidget(tabs)
        
        import_group = QGroupBox("Opcje importu")
        import_layout = QVBoxLayout()
        
        options_layout = QHBoxLayout()
        
        self.use_server_names = QCheckBox("Użyj nazw z serwera TVHeadend")
        self.use_server_names.setChecked(True)
        self.use_server_names.setToolTip("Zaznaczone: użyje nazw z serwera TVH\nOdznaczone: użyje nazw z listy zdalnej")
        options_layout.addWidget(self.use_server_names)
        
        self.create_tags_check = QCheckBox("Twórz tagi z kategorii")
        self.create_tags_check.setChecked(True)
        options_layout.addWidget(self.create_tags_check)
        options_layout.addStretch()
        
        import_layout.addLayout(options_layout)
        
        self.import_btn = QPushButton("Importuj bouquety do TVHeadend")
        self.import_btn.clicked.connect(self.start_import)
        self.import_btn.setEnabled(False)
        import_layout.addWidget(self.import_btn)
        
        self.progress_bar = QProgressBar()
        import_layout.addWidget(self.progress_bar)
        
        self.status_text = QTextEdit()
        self.status_text.setMaximumHeight(100)
        self.status_text.setReadOnly(True)
        import_layout.addWidget(self.status_text)
        
        import_group.setLayout(import_layout)
        layout.addWidget(import_group)
        
    def connect_tvh(self):
        try:
            host = self.host_input.text()
            port = self.port_input.text()
            user = self.user_input.text()
            password = self.pass_input.text()
            
            self.api = TVHeadendAPI(host, port, user, password)
            self.services = self.api.get_services()
            
            self.services_label.setText(f"Status: Połączony - znaleziono {len(self.services)} usług")
            self.parse_btn.setEnabled(True)
            
            self.services_table.setRowCount(len(self.services))
            for i, service in enumerate(self.services):
                self.services_table.setItem(i, 0, QTableWidgetItem(service.get('svcname', '')))
                self.services_table.setItem(i, 1, QTableWidgetItem(service.get('svctype', '')))
                self.services_table.setItem(i, 2, QTableWidgetItem(service.get('uuid', '')))
            
            self.status_text.append(f"✓ Połączono z TVHeadend ({len(self.services)} usług)")
            
        except Exception as e:
            QMessageBox.critical(self, "Błąd połączenia", str(e))
            self.services_label.setText("Status: Błąd połączenia")
    
    def parse_bouquet(self):
        try:
            url = self.url_input.text()
            if not url:
                QMessageBox.warning(self, "Błąd", "Podaj URL listy kanałów")
                return
            
            self.bouquets = BouquetParser.parse_satkurier(url)
            
            preview = ""
            total_channels = 0
            for category, channels in self.bouquets.items():
                preview += f"\n{'='*80}\n{category} ({len(channels)} kanałów)\n{'='*80}\n"
                for ch in channels[:10]:
                    preview += f"{ch['number']:3d}. {ch['name']}\n"
                
                if len(channels) > 10:
                    preview += f"... i {len(channels) - 10} więcej\n"
                total_channels += len(channels)
            
            self.preview_text.setText(preview)
            self.status_text.append(f"✓ Pobrano listę: {len(self.bouquets)} kategorii, {total_channels} kanałów")
            
            if self.services:
                self.import_btn.setEnabled(True)
            
        except Exception as e:
            QMessageBox.critical(self, "Błąd parsowania", str(e))
    
    def start_import(self):
        if not self.api or not self.bouquets:
            return
        
        self.import_btn.setEnabled(False)
        use_service_names = self.use_server_names.isChecked()
        create_tags = self.create_tags_check.isChecked()
        
        self.worker = ImportWorker(self.api, self.bouquets, self.services, use_service_names, create_tags)
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.import_finished)
        self.worker.start()
    
    def update_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.status_text.append(message)
    
    def import_finished(self, success, message):
        self.import_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, "Sukces", message)
        else:
            QMessageBox.critical(self, "Błąd", message)


def main():
    app = QApplication(sys.argv)
    
    font = QFont()
    font.setPointSize(9)
    app.setFont(font)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()