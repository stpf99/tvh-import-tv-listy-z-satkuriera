#!/usr/bin/env python3
"""
TVHeadend Bouquet Manager - Ulepszona wersja parsera
Zmiany:
- Lepsze rozpoznawanie nagłówków kategorii
- Wsparcie dla różnych struktur HTML
- Debugowanie parsowania
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
            url = f"{self.base_url}/api/idnode/save"
            updates = {'uuid': channel_uuid}
            if tags is not None:
                updates['tags'] = tags
            if number is not None:
                updates['number'] = number
            if name is not None:
                updates['name'] = name
            
            # Format dla idnode/save to {"node": [lista obiektów]}
            data = {'node': json.dumps([updates])}
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
        """Normalizuje nazwę kanału do porównywania"""
        if not name:
            return ""
        
        normalized = name.lower()
        normalized = re.sub(r'\b(hd|sd|uhd|4k|ud)\b', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\b(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\b', '', normalized, flags=re.IGNORECASE)
        normalized = re.sub(r'\s+d\s+d\s*$', '', normalized)
        normalized = re.sub(r'\s+d\s*$', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        normalized = re.sub(r'[^\w\s\+\-]', '', normalized)
        
        return normalized
    
    @staticmethod
    def clean_channel_name(name):
        """Czyści nazwę kanału do zapisania"""
        if not name:
            return ""
        
        cleaned = name
        cleaned = re.sub(r'\s*(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s+D\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s*-\s*$', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        quality_match = re.search(r'\b(HD|SD|UHD|4K)\b', cleaned, flags=re.IGNORECASE)
        if quality_match:
            quality = quality_match.group(1).upper()
            cleaned = re.sub(r'\s*\b(HD|SD|UHD|4K)\b\s*', ' ', cleaned, flags=re.IGNORECASE).strip()
            cleaned = f"{cleaned} {quality}"
        
        return cleaned
    
    @staticmethod
    def is_category_header(cells, text):
        """
        Rozpoznaje czy wiersz to nagłówek kategorii
        """
        if not text or len(text) < 3:
            return False
        
        # Metoda 1: Komórka z colspan (typowe nagłówki)
        if len(cells) == 1 and cells[0].get('colspan'):
            return True
        
        # Metoda 2: Komórka <th> zamiast <td>
        if cells[0].name == 'th':
            return True
        
        # Metoda 3: Komórka z klasą sugerującą nagłówek
        cell_class = cells[0].get('class', [])
        if any(cls in ['header', 'category', 'group', 'title'] for cls in cell_class):
            return True
        
        # Metoda 4: Tekst w <strong> lub <b>
        if cells[0].find(['strong', 'b']):
            # Sprawdź czy to cały tekst w komórce jest pogrubiony
            strong_text = cells[0].find(['strong', 'b']).get_text(strip=True)
            if len(strong_text) >= len(text) * 0.8:  # 80% tekstu pogrubionego
                return True
        
        # Metoda 5: Heurystyka - tekst bez cyfr i parametrów technicznych
        # Typowe kanały mają częstotliwości, polaryzacje itp.
        has_frequency = re.search(r'\d{1,2}[.,]\d{3}', text)
        has_sr = re.search(r'\b\d{5}\b', text)
        has_polarization = re.search(r'\b[VHLR]\b', text)
        has_modulation = re.search(r'DVB-[ST]', text, flags=re.IGNORECASE)
        
        # Jeśli brak parametrów technicznych, może to być kategoria
        if not (has_frequency or has_sr or has_polarization or has_modulation):
            # Sprawdź czy tekst zawiera słowa kluczowe kategorii
            category_keywords = [
                'pakiet', 'kanały', 'kanaly', 'sport', 'filmowe', 'informacyjne',
                'muzyczne', 'dziecięce', 'lifestyle', 'dokumentalne', 'premium',
                'podstawowe', 'rozszerzone', 'dodatkowe', 'hd', 'sd', 'ultra'
            ]
            text_lower = text.lower()
            if any(keyword in text_lower for keyword in category_keywords):
                return True
            
            # Lub jeśli tekst jest krótki i wygląda jak tytuł
            if len(text.split()) <= 5 and len(text) < 50:
                # Nie zawiera cyfr na początku (numery kanałów)
                if not re.match(r'^\d+\.?\s+', text):
                    return True
        
        return False
    
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
                    
                    # Pobierz pełny tekst z wiersza
                    full_text = ' '.join(cell.get_text(strip=True) for cell in cells)
                    
                    if not full_text:
                        continue
                    
                    # Sprawdź czy to nagłówek kategorii
                    if BouquetParser.is_category_header(cells, full_text):
                        current_category = full_text
                        if current_category not in bouquets:
                            bouquets[current_category] = []
                        continue
                    
                    # W przeciwnym razie próbuj sparsować jako kanał
                    if full_text.isdigit():  # Pomijaj wiersze z samymi cyframi
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
    """Wątek do importu bouquetów"""
    
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
            total_channels = sum(len(channels) for channels in self.bouquets.values())
            processed = 0
            matched = 0
            created_channels = 0
            updated_channels = 0
            
            self.progress.emit(0, "Pobieranie istniejących tagów...")
            
            existing_tags = {tag['name']: tag['uuid'] for tag in self.api.get_tags()}
            
            # Mapowanie usług z obsługą duplikatów
            services_map = {}
            for service in self.services:
                name = service.get('svcname', '')
                if name:
                    normalized = BouquetParser.normalize_channel_name(name)
                    if normalized not in services_map:
                        services_map[normalized] = []
                    services_map[normalized].append(service)
            
            self.progress.emit(5, f"Znaleziono {len(services_map)} unikalnych nazw usług")
            
            self.progress.emit(10, "Pobieranie istniejących kanałów...")
            existing_channels = self.api.get_channels()
            channels_by_service = {}
            for ch in existing_channels:
                services = ch.get('services', [])
                if services:
                    for svc_uuid in services:
                        channels_by_service[svc_uuid] = ch
            
            self.progress.emit(15, f"Znaleziono {len(existing_channels)} istniejących kanałów")
            
            processed_services = set()
            
            tag_index = 0
            for category, channels in self.bouquets.items():
                self.progress.emit(
                    15 + int((processed / total_channels) * 70),
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
                            15 + int((processed / total_channels) * 70),
                            f"  ✓ Utworzono tag '{category}'"
                        )
                
                for channel_info in channels:
                    channel_name = channel_info['name']
                    channel_number = channel_info['number']
                    
                    normalized_search = BouquetParser.normalize_channel_name(channel_name)
                    
                    best_match = None
                    best_score = 0
                    best_service_name = ""
                    
                    search_variants = [
                        normalized_search,
                        normalized_search.replace(' ', ''),
                        normalized_search.replace('+', ' plus'),
                        normalized_search.replace('+', ''),
                    ]
                    
                    # Szukaj w mapie (która może mieć wiele usług na nazwę)
                    for service_norm_name, service_list in services_map.items():
                        for variant in search_variants:
                            score = SequenceMatcher(None, variant, service_norm_name).ratio()
                            if score > best_score:
                                # Wybierz pierwszą nieprzetworzoną usługę z listy
                                for service in service_list:
                                    if service['uuid'] not in processed_services:
                                        best_score = score
                                        best_match = service
                                        best_service_name = service.get('svcname', '')
                                        break
                    
                    if best_match and best_score >= self.threshold:
                        service_uuid = best_match['uuid']
                        processed_services.add(service_uuid)
                        
                        if service_uuid in channels_by_service:
                            existing_channel = channels_by_service[service_uuid]
                            tags = existing_channel.get('tags', [])
                            if tag_uuid and tag_uuid not in tags:
                                tags.append(tag_uuid)
                            
                            self.api.update_channel(
                                existing_channel['uuid'],
                                tags=tags,
                                number=channel_number,
                                name=channel_name
                            )
                            updated_channels += 1
                            self.progress.emit(
                                15 + int((processed / total_channels) * 70),
                                f"  ✓ Zaktualizowano: {channel_name} <- {best_service_name} ({best_score:.0%})"
                            )
                        else:
                            tags = [tag_uuid] if tag_uuid else []
                            self.api.create_channel_from_service(
                                service_uuid,
                                channel_name,
                                tags=tags,
                                number=channel_number
                            )
                            created_channels += 1
                            self.progress.emit(
                                15 + int((processed / total_channels) * 70),
                                f"  ✓ Utworzono: {channel_name} <- {best_service_name} ({best_score:.0%})"
                            )
                        
                        matched += 1
                    else:
                        self.progress.emit(
                            15 + int((processed / total_channels) * 70),
                            f"  ✗ Nie znaleziono: {channel_name} (najlepsze: {best_score:.0%})"
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
            import traceback
            error_details = traceback.format_exc()
            self.finished.emit(False, f"Błąd importu: {str(e)}\n\n{error_details}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api = None
        self.services = []
        self.bouquets = {}
        self.worker = None
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
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://satkurier.pl/news/234203/lista-kanalow-polsat-box.html")
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
        options_layout.addWidget(QLabel("Próg podobieństwa:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(5, 100)
        self.threshold_spin.setValue(5)
        self.threshold_spin.setSuffix("%")
        options_layout.addWidget(self.threshold_spin)
        
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
        
        # Sprawdź czy import już trwa
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "Uwaga", "Import już trwa!")
            return
        
        self.import_btn.setEnabled(False)
        threshold = self.threshold_spin.value() / 100.0
        create_tags = self.create_tags_check.isChecked()
        
        self.worker = ImportWorker(self.api, self.bouquets, self.services, threshold, create_tags)
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
