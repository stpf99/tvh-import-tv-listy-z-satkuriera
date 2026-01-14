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
from urllib.parse import urljoin



class TVHeadendAPI:
    """Klasa do komunikacji z TVHeadend API (dodano obsługę multipleksów dla częstotliwości)"""
    
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
    
    def get_multiplexes(self):
        """
        Pobiera listę multipleksów (transponderów), aby pobrać ich częstotliwości.
        Zwraca słownik {mux_uuid: frequency_khz}
        """
        try:
            url = f"{self.base_url}/api/mpegts/multiplex/grid"
            params = {'start': 0, 'limit': 999999}
            response = requests.get(url, params=params, auth=self.auth, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            muxes = {}
            for entry in data.get('entries', []):
                # Częstotliwość w TVH jest często podana w Hz
                muxes[entry['uuid']] = entry.get('freq', 0)
            return muxes
        except Exception as e:
            # Jeśli się nie uda (np. starsza wersja TVH), zwracamy pusty słownik
            print(f"Ostrzeżenie: Nie można pobrać multipleksów: {e}")
            return {}

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
            url = f"{self.base_url}/api/channel/create"
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
            url = f"{self.base_url}/api/channel/create"
            updates = {'uuid': channel_uuid}
            if tags is not None:
                updates['tags'] = tags
            if number is not None:
                updates['number'] = number
            if name is not None:
                updates['name'] = name
            data = {'conf': json.dumps(updates)}
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
    """Klasa do parsowania list kanałów (obsługa specyficzna dla SatKurier.pl z paginacją w nazwie pliku)"""
    
    @staticmethod
    def normalize_channel_name(name):
        """
        Normalizuje nazwę do klucza mapowania.
        Zachowuje litery i CYFRY (np. TV4, TVP 2).
        """
        if not name:
            return ""
        
        normalized = name.lower()
        normalized = re.sub(r'[^a-z0-9]', '', normalized)
        return normalized
    
    @staticmethod
    def clean_channel_name(name):
        """Czyści nazwę kanału do zapisu (usuwa HD, SD, gatunki, parametry)"""
        if not name:
            return ""
        
        cleaned = name
        
        # Gatunki
        genres = r'\b(muzyczny|informacyjny|uniwersalny|filmowy|sportowy|religijny|dokumentalny|rozrywkowy|dla dzieci|telezakupowy|prawniczy|kulinarny|motoryzacyjny|erotyczny|turystyczny|lifestyle|dla młodzieży)\b'
        cleaned = re.sub(genres, '', cleaned, flags=re.IGNORECASE)

        # Parametry techniczne
        cleaned = re.sub(r'\s*(dvb-[st]\d?(?:/\w+)?|db-s\d?/\w+)\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*\b(HD|SD|UHD|4K|UD)\b\s*', ' ', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\d{1,2}[.,]\d{3}', '', cleaned)  # częstotliwość (na wypadek jeśli jest w nazwie)
        cleaned = re.sub(r'\b[VHLR]\b', '', cleaned)
        cleaned = re.sub(r'\b\d{5}\b', '', cleaned)  # SR
        cleaned = re.sub(r'\d/\d', '', cleaned)  # FEC
        cleaned = re.sub(r'\bs\d/\w+\b', '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s+D\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s+D\s*$', '', cleaned)
        cleaned = re.sub(r'\s*[-+]\s*$', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned
    
    @staticmethod
    def create_mapping_key(name):
        return BouquetParser.normalize_channel_name(name)
    
    @staticmethod
    def parse_satkurier(base_url):
        """Parsowanie listy z obsługą podstron SatKurier (format: nazwa-2.html)"""
        from urllib.parse import urljoin, urlparse

        try:
            pages_to_process = set([base_url])
            pages_discovered = set([base_url])
            
            try:
                response = requests.get(base_url, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Analiza podstawowej nazwy pliku URL do wykrywania wzorca podstron
                parsed_base = urlparse(base_url)
                base_path = parsed_base.path
                base_name_no_ext = base_path
                if '.' in base_name_no_ext:
                    base_name_no_ext = base_name_no_ext.rsplit('.', 1)[0] # usuwamy .html
                
                # Usuwamy ending number z aktualnego URL, aby znaleźć "korzeń" (root)
                # np. lista-kanalow-canal-1 -> lista-kanalow-canal
                base_name_no_ext = re.sub(r'-\d+$', '', base_name_no_ext)
                
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    full_url = urljoin(base_url, href)
                    
                    # Sprawdzenie 1: Standardowa paginacja (?page=2)
                    if 'page=' in href.lower():
                        if full_url not in pages_discovered:
                            pages_to_process.add(full_url)
                            pages_discovered.add(full_url)
                        continue
                    
                    # Sprawdzenie 2: Specyficzna dla SatKurier (format pliku: nazwa-2.html)
                    # Sprawdzamy czy link należy do tej samej domeny
                    if not full_url.startswith(parsed_base.scheme + "://" + parsed_base.netloc):
                        continue

                    parsed_link = urlparse(full_url)
                    link_name_no_ext = parsed_link.path
                    if link_name_no_ext.endswith('.html'):
                        link_name_no_ext = link_name_no_ext.rsplit('.', 1)[0]
                    
                    # Czy link zaczyna się od nazwy bazowej?
                    if link_name_no_ext.startswith(base_name_no_ext):
                        # Sprawdzamy czy link ma sufiks numeryczny (oznaczający podstronę)
                        suffix = link_name_no_ext[len(base_name_no_ext):]
                        if re.match(r'-\d+$', suffix):
                            if full_url not in pages_discovered:
                                pages_to_process.add(full_url)
                                pages_discovered.add(full_url)
                                
            except Exception as e:
                print(f"Ostrzeżenie: Błąd wykrywania podstron: {e}")

            print(f"Znaleziono {len(pages_to_process)} stron do przetworzenia.")
            all_bouquets = {}
            
            for page_url in pages_to_process:
                try:
                    print(f"Pobieranie: {page_url}")
                    r = requests.get(page_url, timeout=10)
                    r.raise_for_status()
                    s = BeautifulSoup(r.content, 'html.parser')
                    
                    page_channels = []
                    current_category = "Bez kategorii"
                    tables = s.find_all('table')
                    
                    for table in tables:
                        rows = table.find_all('tr')
                        name_col_index = -1
                        freq_col_index = -1
                        header_detected = False
                        
                        for row in rows:
                            cells = row.find_all(['td', 'th'])
                            if not cells: continue
                            
                            header_texts = [cell.get_text(strip=True).lower() for cell in cells]
                            keywords = ['nazwa', 'name', 'częstotliwość', 'freq', 'transponder', 'tp', 'pol', 'sr', 'dostawca', 'nr', 'rozdzielczość', 'parametry']
                            match_count = sum(1 for kw in keywords if kw in ' '.join(header_texts))
                            
                            if match_count >= 2:
                                for i, text in enumerate(header_texts):
                                    if 'nazwa' in text and 'pakiet' not in text and 'gatunek' not in text:
                                        name_col_index = i
                                    if 'freq' in text or 'częstotliwość' in text:
                                        freq_col_index = i
                                        
                                header_detected = True
                                continue
                            
                            if len(cells) == 1 and cells[0].get('colspan'):
                                header_text = cells[0].get_text(strip=True)
                                if header_text and len(header_text) > 2:
                                    current_category = header_text
                                continue
                            
                            if len(cells) < 2: continue
                                
                            # Pobranie nazwy
                            raw_name = ""
                            if name_col_index != -1 and name_col_index < len(cells):
                                raw_name = cells[name_col_index].get_text(separator=' ', strip=True)
                            else:
                                raw_name = ' '.join([cell.get_text(separator=' ', strip=True) for cell in cells])
                            
                            # Pobranie częstotliwości
                            raw_freq = ""
                            if freq_col_index != -1 and freq_col_index < len(cells):
                                raw_freq = cells[freq_col_index].get_text(separator=' ', strip=True)
                            
                            if not raw_name or raw_name.isdigit(): continue
                            if re.match(r'^[\s\-_=]+$', raw_name) or len(raw_name) < 3: continue
                            
                            header_str = ' '.join(header_texts)
                            if any(kw in header_str for kw in ['nr nazwa', 'rozdzielczość parametry', 'parametry techniczne']):
                                continue

                            channel_info = BouquetParser.parse_channel_info(raw_name, raw_freq)
                            if channel_info and channel_info['name']:
                                channel_info['category'] = current_category
                                page_channels.append(channel_info)
                    
                    for ch in page_channels:
                        cat = ch['category']
                        if cat not in all_bouquets: all_bouquets[cat] = []
                        all_bouquets[cat].append(ch)
                        
                except Exception as e:
                    print(f"Błąd strony {page_url}: {e}")

            for cat in all_bouquets:
                for idx, ch in enumerate(all_bouquets[cat], 1):
                    ch['number'] = idx
            
            return all_bouquets
        except Exception as e:
            raise Exception(f"Błąd parsowania: {str(e)}")
    
    @staticmethod
    def parse_channel_info(text, freq_text=None):
        """
        Parsuje informacje o kanale. 
        freq_text: opcjonalny tekst częstotliwości z osobnej kolumny.
        """
        text = re.sub(r'^\d+\.?\s*', '', text)
        if not text or len(text) < 2: return None
        
        info = {
            'name': '', 'full_text': text, 'quality': '', 'frequency': '', 
            'polarization': '', 'symbol_rate': '', 'fec': '', 'modulation': ''
        }
        
        if freq_text:
            freq_match = re.search(r'(\d{1,2}[.,]\d{3})', freq_text)
            if freq_match:
                info['frequency'] = freq_match.group(1)
        else:
            freq_match = re.search(r'(\d{1,2}[.,]\d{3})', text)
            if freq_match: info['frequency'] = freq_match.group(1)
        
        pol_match = re.search(r'\b([VHLR])\b', text)
        if pol_match: info['polarization'] = pol_match.group(1)
        
        sr_match = re.search(r'\b(\d{5})\b', text)
        if sr_match: info['symbol_rate'] = sr_match.group(1)
        
        fec_match = re.search(r'(\d/\d)', text)
        if fec_match: info['fec'] = fec_match.group(1)
        
        mod_match = re.search(r'(DVB-[ST]\d?(?:/\w+)?|DB-S\d?/\w+)', text, flags=re.IGNORECASE)
        if mod_match: info['modulation'] = mod_match.group(1)
        
        quality_match = re.search(r'\b(HD|SD|UHD|4K|UD)\b', text, flags=re.IGNORECASE)
        if quality_match: info['quality'] = quality_match.group(1).upper()
        
        info['name'] = BouquetParser.clean_channel_name(text)
        return info

class ImportWorker(QThread):
    """Wątek do importu (poprawiona obsługa częstotliwości)"""
    
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    
    def __init__(self, api, bouquets, services, use_service_names=True, create_tags=True):
        super().__init__()
        self.api = api
        self.bouquets = bouquets
        self.services = services
        self.use_service_names = use_service_names
        self.create_tags = create_tags
        
    def get_freq_mhz_from_str(self, freq_str):
        """Konwertuje string częstotliwości (np. '11,508' lub '11642') na MHz (int)"""
        if not freq_str:
            return 0
        
        freq_str = freq_str.replace(',', '.')
        try:
            val = float(freq_str)
            # Jeśli wartość jest poniżej 1000, to pewnie GHz (np. 11.508), zamień na MHz
            if val < 1000:
                return int(val * 1000)
            else:
                return int(val)
        except:
            return 0

    def run(self):
        try:
            total_channels = sum(len(channels) for channels in self.bouquets.values())
            processed = 0
            matched = 0
            created_channels = 0
            updated_channels = 0
            
            self.progress.emit(0, "Pobieranie istniejących tagów...")
            existing_tags = {tag['name']: tag['uuid'] for tag in self.api.get_tags()}
            
            self.progress.emit(5, "Pobieranie multipleksów...")
            multiplexes = self.api.get_multiplexes()
            
            self.progress.emit(10, "Tworzenie mapy usług z częstotliwościami...")
            services_map = {}
            
            for service in self.services:
                name = service.get('svcname', '')
                if not name:
                    continue
                
                mapping_key = BouquetParser.create_mapping_key(name)
                
                # Pobranie częstotliwości z TVHeadend
                mux_uuid = service.get('multiplex_uuid')
                freq_khz = multiplexes.get(mux_uuid, 0)
                freq_mhz = int(freq_khz / 1000) if freq_khz > 0 else 0
                
                master_key = (mapping_key, freq_mhz)
                
                if master_key not in services_map:
                    services_map[master_key] = service
            
            self.progress.emit(15, f"Mapa usług: {len(services_map)} unikalnych par (Nazwa+Frequ)")
            
            self.progress.emit(16, "Pobieranie istniejących kanałów...")
            existing_channels = self.api.get_channels()
            channels_by_service = {}
            for ch in existing_channels:
                services = ch.get('services', [])
                if services:
                    for svc_uuid in services:
                        channels_by_service[svc_uuid] = ch
            
            self.progress.emit(18, f"Znaleziono {len(existing_channels)} istniejących kanałów")
            
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
                
                for channel_info in channels:
                    original_name = channel_info['name']
                    channel_number = channel_info['number']
                    
                    mapping_key = BouquetParser.create_mapping_key(original_name)
                    
                    # Częstotliwość z listy zdalnej (teraz powinna być poprawnie wyciągnięta z kolumny)
                    remote_freq_str = channel_info.get('frequency', '')
                    remote_freq_mhz = self.get_freq_mhz_from_str(remote_freq_str)
                    
                    remote_key = (mapping_key, remote_freq_mhz)
                    
                    if not mapping_key:
                        self.progress.emit(
                            18 + int((processed / total_channels) * 72),
                            f"  ✗ Pominięto (brak nazwy): {original_name}"
                        )
                        processed += 1
                        continue
                    
                    if remote_key in services_map:
                        service = services_map[remote_key]
                        service_uuid = service['uuid']
                        
                        if service_uuid in processed_services:
                            self.progress.emit(
                                18 + int((processed / total_channels) * 72),
                                f"  ⊗ Pominięto (duplikat): {original_name} [{remote_freq_mhz} MHz]"
                            )
                            processed += 1
                            continue
                        
                        processed_services.add(service_uuid)
                        
                        if self.use_service_names:
                            final_name = BouquetParser.clean_channel_name(service.get('svcname', ''))
                        else:
                            final_name = BouquetParser.clean_channel_name(original_name)
                        
                        service_original = service.get('svcname', '')
                        
                        if service_uuid in channels_by_service:
                            # Aktualizacja
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
                                f"  ✓ Zaktualizowano: {final_name} [{remote_freq_mhz} MHz]"
                            )
                        else:
                            # Tworzenie
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
                                f"  ✓ Utworzono: {final_name} [{remote_freq_mhz} MHz]"
                            )
                        
                        matched += 1
                    else:
                        self.progress.emit(
                            18 + int((processed / total_channels) * 72),
                            f"  ✗ Nie znaleziono: {original_name} [{remote_freq_mhz} MHz]"
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
        self.host_input = QLineEdit("192.168.1.238")
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