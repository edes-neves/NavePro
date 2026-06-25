
import sys
import os
import json
import glob
import re
import subprocess
import signal
import tkinter as tk
from datetime import datetime
import urllib.request
import urllib.parse
import threading
import time

# Tenta importar python-xlib para controle preciso de janelas
try:
    import Xlib.display
    import Xlib.X
    import Xlib.Xatom
    HAS_XLIB = True
except ImportError:
    HAS_XLIB = False
    print("⚠️ python-xlib não encontrada. Usando fallback com xdotool (menos preciso).")
    print("   Para melhor controle, instale: pip install python-xlib")

# ===== CONFIGURAÇÕES =====
CONFIG_FILE = "config.json"
PLAYER_PADRAO = "smplayer"

# ===== FUNÇÃO PARA OBTER TEMPERATURA =====
def _normalizar_texto(texto):
    return re.sub(r'\s+', ' ', str(texto or '').strip()).lower()


def _estado_para_nome(estado):
    mapa = {
        'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia',
        'CE': 'Ceará', 'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás',
        'MA': 'Maranhão', 'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
        'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco', 'PI': 'Piauí',
        'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte', 'RS': 'Rio Grande do Sul',
        'RO': 'Rondônia', 'RR': 'Roraima', 'SC': 'Santa Catarina', 'SP': 'São Paulo',
        'SE': 'Sergipe', 'TO': 'Tocantins'
    }
    return mapa.get(estado.upper(), estado)


def obter_temperatura(cidade, estado):
    """Obtém a temperatura atual usando a API Open-Meteo e prioriza cidade + estado."""
    try:
        cidade = cidade.strip()
        estado = estado.strip().upper()
        estado_nome = _estado_para_nome(estado)
        consultas = []

        if estado:
            consultas.append(f"{cidade}, {estado_nome}, Brasil")
            consultas.append(f"{cidade}, {estado}, Brasil")
            consultas.append(f"{cidade}, {estado_nome}")
        consultas.append(cidade)

        for consulta in consultas:
            geo_url = (
                f"https://geocoding-api.open-meteo.com/v1/search?"
                f"name={urllib.parse.quote(consulta)}&count=5&language=pt&format=json&country=BR"
            )
            if estado:
                geo_url += f"&admin1={urllib.parse.quote(estado_nome)}"

            try:
                with urllib.request.urlopen(geo_url, timeout=5) as response:
                    geo_data = json.loads(response.read().decode())
            except Exception:
                continue

            if 'results' in geo_data and geo_data['results']:
                resultado = None
                resultados_estado = []
                for item in geo_data['results']:
                    nome = _normalizar_texto(item.get('name', ''))
                    admin1 = _normalizar_texto(item.get('admin1', ''))
                    if _normalizar_texto(cidade) == nome:
                        if not estado or admin1 in {_normalizar_texto(estado_nome), _normalizar_texto(estado)}:
                            resultado = item
                            break
                        resultados_estado.append(item)

                if resultado is None and len(geo_data['results']) == 1:
                    resultado = geo_data['results'][0]

                if resultado is not None:
                    if estado:
                        admin1 = _normalizar_texto(resultado.get('admin1', ''))
                        if admin1 not in {_normalizar_texto(estado_nome), _normalizar_texto(estado)}:
                            return f"A cidade informada não pertence ao estado de {estado_nome}"
                elif estado and resultados_estado:
                    return f"A cidade informada não pertence ao estado de {estado_nome}"
                elif estado and not resultados_estado and geo_data['results']:
                    return f"A cidade informada não pertence ao estado de {estado_nome}"
                    lat = resultado.get('latitude')
                    lon = resultado.get('longitude')
                    if lat is None or lon is None:
                        continue

                    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                    with urllib.request.urlopen(weather_url, timeout=5) as response:
                        weather_data = json.loads(response.read().decode())

                    if 'current_weather' in weather_data:
                        temp = weather_data['current_weather']['temperature']
                        return f"{temp}°C"
                    return "Erro ao obter temperatura"

        # Fallback para nominatim
        try:
            geo_url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(f'{cidade}, {estado_nome}, Brasil')}&format=json&limit=3"
            req = urllib.request.Request(geo_url, headers={'User-Agent': 'HinarioApp/1.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                geo_data = json.loads(response.read().decode())
                if geo_data:
                    for item in geo_data:
                        display_name = _normalizar_texto(item.get('display_name', ''))
                        if _normalizar_texto(cidade) in display_name:
                            if estado and _normalizar_texto(estado_nome) not in display_name:
                                return f"A cidade informada não pertence ao estado de {estado_nome}"
                            if estado and _normalizar_texto(estado_nome) in display_name:
                                lat = float(item['lat'])
                                lon = float(item['lon'])
                                weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                                with urllib.request.urlopen(weather_url, timeout=5) as response:
                                    weather_data = json.loads(response.read().decode())
                                if 'current_weather' in weather_data:
                                    temp = weather_data['current_weather']['temperature']
                                    return f"{temp}°C"
                            lat = float(item['lat'])
                            lon = float(item['lon'])
                            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                            with urllib.request.urlopen(weather_url, timeout=5) as response:
                                weather_data = json.loads(response.read().decode())
                            if 'current_weather' in weather_data:
                                temp = weather_data['current_weather']['temperature']
                                return f"{temp}°C"
                    lat = float(geo_data[0]['lat'])
                    lon = float(geo_data[0]['lon'])
                    weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
                    with urllib.request.urlopen(weather_url, timeout=5) as response:
                        weather_data = json.loads(response.read().decode())
                    if 'current_weather' in weather_data:
                        temp = weather_data['current_weather']['temperature']
                        return f"{temp}°C"
        except Exception:
            pass

        return "Cidade não encontrada"
    except Exception as e:
        print(f"Erro ao obter temperatura: {e}")
        return "Erro"


# ===== DETECÇÃO DE MONITORES =====
def get_monitors_config():
    """Detecta monitores - múltiplos métodos de fallback"""
    try:
        from screeninfo import get_monitors
        monitors = get_monitors()
        if monitors:
            print("✅ screeninfo funcionou")
            return monitors
    except:
        pass
    
    try:
        root = tk.Tk()
        root.withdraw()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()
        
        class Monitor:
            def __init__(self, x, y, w, h, name="Monitor"):
                self.x = x
                self.y = y
                self.width = w
                self.height = h
                self.name = name
        
        if screen_width > 2500:
            half = screen_width // 2
            return [
                Monitor(0, 0, half, screen_height, "Monitor 1"),
                Monitor(half, 0, half, screen_height, "Monitor 2")
            ]
        else:
            return [Monitor(0, 0, screen_width, screen_height, "Monitor 1")]
    except:
        pass
    
    try:
        result = subprocess.run(['xrandr'], capture_output=True, text=True)
        connected = []
        for line in result.stdout.split('\n'):
            if ' connected' in line and '+' in line:
                parts = line.split()
                for p in parts:
                    if 'x' in p and '+' in p:
                        size_pos = p.split('+')
                        if len(size_pos) >= 3:
                            size = size_pos[0].split('x')
                            x = int(size_pos[1])
                            y = int(size_pos[2])
                            w = int(size[0])
                            h = int(size[1])
                            class Monitor:
                                def __init__(self, x, y, w, h, name="Monitor"):
                                    self.x = x
                                    self.y = y
                                    self.width = w
                                    self.height = h
                                    self.name = name
                            connected.append(Monitor(x, y, w, h, parts[0]))
        if connected:
            return connected
    except:
        pass
    
    class Monitor:
        def __init__(self, x, y, w, h, name="Monitor"):
            self.x = x
            self.y = y
            self.width = w
            self.height = h
            self.name = name
    return [
        Monitor(0, 0, 1920, 1080, "Monitor 1"),
        Monitor(1920, 0, 1920, 1080, "Monitor 2")
    ]


# ===== JANELA DO TELÃO =====
class TelaoWindow:
    def __init__(self, monitor_index=1):
        self.root = tk.Tk()
        self.root.title("TELÃO")
        
        monitors = get_monitors_config()
        print(f"🖥️ Monitores detectados: {len(monitors)}")
        for i, m in enumerate(monitors):
            print(f"   Monitor {i+1}: {m.width}x{m.height} em ({m.x},{m.y})")
        
        if len(monitors) >= monitor_index:
            monitor = monitors[monitor_index - 1]
        elif len(monitors) > 1:
            monitor = monitors[1]
        else:
            monitor = monitors[0]
        
        geometry = f"{monitor.width}x{monitor.height}+{monitor.x}+{monitor.y}"
        print(f"✅ TELÃO: {geometry}")
        
        self.root.geometry(geometry)
        self.root.configure(bg='black')
        self.root.attributes('-alpha', 0.55)
        self.root.attributes('-topmost', False)
        self.root.lower()
        
        self.main_frame = tk.Frame(self.root, bg='black')
        self.main_frame.pack(fill='both', expand=True)
        
        self.canvas = tk.Canvas(self.main_frame, bg='black', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        
        # Texto da hora
        self.overlay_text = self.canvas.create_text(
            0, 0, text="", fill="#F5BE08", anchor="center",
            font=("Digital-7", 250, "normal")
        )
        
        # Texto da temperatura
        self.temp_text = self.canvas.create_text(
            0, 0, text="", fill="#F5BE08", anchor="center",
            font=("Digital-7", 120, "normal")
        )
        
        self.canvas.bind("<Configure>", self._centralizar)
        self.root.bind("<Escape>", self.fechar)
        self.root.bind("<F11>", self.fechar)
        
        self.rodando = True
        self.mostrando_relogio = True
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
        self.root.update()
    
    def _centralizar(self, event=None):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.canvas.coords(self.overlay_text, w/2, h/2 - 100)
        self.canvas.coords(self.temp_text, w/2, h/2 + 130)
    
    def mostrar_relogio(self, texto, temperatura=""):
        self.mostrando_relogio = True
        self.root.deiconify()
        self.root.attributes('-alpha', 0.55)
        self.canvas.itemconfig(self.overlay_text, text=texto)
        self.canvas.itemconfig(self.overlay_text, state="normal")
        
        if temperatura:
            self.canvas.itemconfig(self.temp_text, text=temperatura)
            self.canvas.itemconfig(self.temp_text, state="normal")
        else:
            self.canvas.itemconfig(self.temp_text, text="")
            self.canvas.itemconfig(self.temp_text, state="hidden")
        
        self.root.lower()
    
    def preparar_video(self):
        self.mostrando_relogio = False
        self.root.attributes('-alpha', 0.0)
        self.root.withdraw()
    
    def restaurar_tela(self):
        self.root.deiconify()
        self.root.attributes('-alpha', 0.55)
        self.mostrando_relogio = True
        self.root.lower()
        self.root.after(100, self.root.lower)
        self.root.after(500, self.root.lower)
    
    def update(self):
        if self.rodando:
            try:
                self.root.update()
            except:
                pass
    
    def fechar(self, event=None):
        self.rodando = False
        try:
            self.root.destroy()
        except:
            pass


# ===== PLAYER =====
class MediaPlayer:
    def __init__(self, monitor_index=1, player_cmd="smplayer"):
        self.playlist = []
        self.index = 0
        self.is_playing = False
        self.is_paused = False
        self.process = None
        self.monitor_index = monitor_index
        self.player_cmd = player_cmd
        self.tempo_inicio = None
        self.tempo_acumulado = 0.0
        self.duracao_total = None
        
        self.telao = TelaoWindow(monitor_index)
        self.on_state_change = None
        self.on_track_change = None
        self.monitorar()
    
    def monitorar(self):
        if self.process and self.process.poll() is not None:
            returncode = self.process.poll()
            if returncode == 0 or returncode == -15 or returncode == -9:
                self.is_playing = False
                self.is_paused = False
                self.telao.restaurar_tela()
                if self.on_state_change:
                    self.on_state_change("ended")
        
        if self.telao.rodando:
            self.telao.root.after(500, self.monitorar)
    
    def carregar_playlist(self, arquivos):
        self.playlist = list(arquivos) if arquivos else []
        self.index = 0
    
    def _get_monitor_geometry(self):
        try:
            monitors = get_monitors_config()
            if len(monitors) >= self.monitor_index:
                monitor = monitors[self.monitor_index - 1]
            elif len(monitors) > 1:
                monitor = monitors[1]
            else:
                monitor = monitors[0]
            return monitor.x, monitor.y, monitor.width, monitor.height
        except:
            return 1920, 0, 1920, 1080
    
    def _matar_processo(self):
        """Mata o processo atual de forma agressiva"""
        if self.process:
            pid = self.process.pid
            print(f"🛑 Matando processo {pid}...")
            
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.3)
                
                try:
                    os.kill(pid, 0)
                    os.kill(pid, signal.SIGKILL)
                except:
                    pass
                
                subprocess.run(f'pkill -9 -P {pid}', shell=True, capture_output=True)
                subprocess.run(f'kill -9 {pid} 2>/dev/null', shell=True, capture_output=True)
                
                if self.player_cmd == "smplayer":
                    subprocess.run('pkill -9 smplayer', shell=True, capture_output=True)
                    subprocess.run('pkill -9 -f smplayer', shell=True, capture_output=True)
                elif self.player_cmd == "vlc":
                    subprocess.run('pkill -9 vlc', shell=True, capture_output=True)
                elif self.player_cmd == "mpv":
                    subprocess.run('pkill -9 mpv', shell=True, capture_output=True)
                
            except Exception as e:
                print(f"Erro ao matar: {e}")
            
            self.process = None

    def _finalizar_player(self):
        try:
            if self.process:
                self._matar_processo()
            if self.player_cmd == "smplayer":
                subprocess.run('pkill -9 smplayer', shell=True, capture_output=True)
                subprocess.run('pkill -9 -f smplayer', shell=True, capture_output=True)
            elif self.player_cmd == "vlc":
                subprocess.run('pkill -9 vlc', shell=True, capture_output=True)
            elif self.player_cmd == "mpv":
                subprocess.run('pkill -9 mpv', shell=True, capture_output=True)
        except Exception as e:
            print(f"Erro ao finalizar player: {e}")
    
    def _tocar_arquivo(self, arquivo):
        # Mata qualquer processo anterior primeiro
        self._matar_processo()
        time.sleep(0.3)
        
        if not os.path.exists(arquivo):
            print(f"❌ Arquivo não encontrado: {arquivo}")
            return False
        
        print(f"🎵 Tocando: {os.path.basename(arquivo)}")
        
        self.telao.preparar_video()
        self.tempo_acumulado = 0.0
        self.tempo_inicio = time.time()
        self.duracao_total = self._obter_duracao_arquivo(arquivo)
        
        mx, my, mw, mh = self._get_monitor_geometry()
        
        try:
            if self.player_cmd == "smplayer":
                cmd = ['smplayer', arquivo, '-fullscreen']
            elif self.player_cmd == "vlc":
                cmd = [
                    'vlc', '--quiet', '--no-osd', '--no-video-title-show',
                    '--play-and-exit', '--fullscreen', '--video-on-top',
                    '--qt-fullscreen-screennumber=1',
                    '--video-x=' + str(mx), '--video-y=' + str(my),
                    '--width=' + str(mw), '--height=' + str(mh),
                    arquivo
                ]
            elif self.player_cmd == "mpv":
                cmd = ['mpv', '--fullscreen', '--screen=1', '--really-quiet', '--no-terminal', arquivo]
            else:
                cmd = ['xdg-open', arquivo]
            
            print(f"🎬 Executando: {' '.join(cmd)}")
            self.process = subprocess.Popen(cmd)
            
            time.sleep(0.5)
            
            self.is_playing = True
            self.is_paused = False
            return True
        except Exception as e:
            print(f"❌ Erro: {e}")
            return False
    
    def _pausar_player(self):
        """Tenta pausar o player via dbus"""
        if self.player_cmd == "vlc":
            try:
                subprocess.run([
                    'dbus-send', '--type=method_call', '--dest=org.mpris.MediaPlayer2.vlc',
                    '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player.PlayPause'
                ], timeout=2, capture_output=True)
                return True
            except:
                pass
        elif self.player_cmd == "smplayer":
            try:
                subprocess.run([
                    'dbus-send', '--type=method_call', '--dest=org.mpris.MediaPlayer2.smplayer',
                    '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player.PlayPause'
                ], timeout=2, capture_output=True)
                return True
            except:
                pass
        
        try:
            if self.process:
                if self.is_paused:
                    os.kill(self.process.pid, signal.SIGCONT)
                    return True
                else:
                    os.kill(self.process.pid, signal.SIGSTOP)
                    return True
        except:
            pass
        return False

    def _obter_duracao_arquivo(self, arquivo):
        if not arquivo or not os.path.exists(arquivo):
            return None
        try:
            resultado = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', arquivo],
                capture_output=True, text=True, timeout=5
            )
            if resultado.returncode == 0 and resultado.stdout.strip():
                return float(resultado.stdout.strip())
        except Exception:
            pass
        return None

    def obter_tempo_decorrido(self):
        if self.tempo_inicio is not None:
            return self.tempo_acumulado + (time.time() - self.tempo_inicio)
        return self.tempo_acumulado
    
    def play_pause(self):
        if self.is_playing and not self.is_paused:
            if self._pausar_player():
                self.is_paused = True
                if self.tempo_inicio is not None:
                    self.tempo_acumulado += time.time() - self.tempo_inicio
                    self.tempo_inicio = None
        elif self.is_paused:
            if self._pausar_player():
                self.is_paused = False
                self.is_playing = True
                self.tempo_inicio = time.time()
        else:
            if self.playlist and self.index < len(self.playlist):
                arquivo = self.playlist[self.index]
                if self._tocar_arquivo(arquivo):
                    if self.on_track_change:
                        self.on_track_change(self.index, arquivo)
    
    def stop(self):
        """Para o player completamente"""
        self._finalizar_player()
        self.is_playing = False
        self.is_paused = False
        self.tempo_inicio = None
        self.tempo_acumulado = 0.0
        self.duracao_total = None
        self.telao.restaurar_tela()
        print("✅ Player parado")
    
    def proximo(self):
        """Próxima música/vídeo"""
        if not self.playlist or self.index >= len(self.playlist) - 1:
            print("⚠️ Não há próximo item")
            return False
        
        print("⏭ Indo para próximo...")
        self.stop()
        time.sleep(0.3)
        
        self.index += 1
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False
    
    def anterior(self):
        """Anterior música/vídeo"""
        if not self.playlist or self.index <= 0:
            print("⚠️ Não há item anterior")
            return False
        
        print("⏮ Voltando para anterior...")
        self.stop()
        time.sleep(0.3)
        
        self.index -= 1
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False
    
    def tocar_indice(self, indice):
        """Toca um índice específico da playlist"""
        if not self.playlist or indice < 0 or indice >= len(self.playlist):
            return False
        
        print(f"🎯 Tocando índice {indice}...")
        self.stop()
        time.sleep(0.3)
        
        self.index = indice
        arquivo = self.playlist[self.index]
        if self._tocar_arquivo(arquivo):
            if self.on_track_change:
                self.on_track_change(self.index, arquivo)
            return True
        return False
    
    def mostrar_relogio(self, texto, temperatura=""):
        if self.telao.mostrando_relogio and not self.is_playing:
            self.telao.mostrar_relogio(texto, temperatura)


# ===== INTERFACE =====
class AppInterface:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("NOVO HASD - PRO")
        self.root.geometry("1200x800")
        self.root.configure(bg='#1a1a2e')
        
        try:
            monitors = get_monitors_config()
            if monitors:
                m = monitors[0]
                self.root.geometry(f"1200x800+{m.x+50}+{m.y+50}")
        except:
            pass
        
        self.config_data = self.carregar_config()
        self.monitor_index = self.config_data.get("monitor", 2)
        self.player_cmd = self.config_data.get("player", PLAYER_PADRAO)
        self.pasta_videos = os.path.expanduser("~/Hinos")
        self.arquivos_encontrados = []
        self.arquivo_atual = None
        self.busca_realizada = False
        
        self.cidade_salva = self.config_data.get("cidade", "")
        self.estado_salvo = self.config_data.get("estado", "")
        self.temperatura_atual = ""
        
        print(f"🎮 Player: {self.player_cmd} | Monitor: {self.monitor_index}")
        
        self.player = MediaPlayer(self.monitor_index, self.player_cmd)
        self.player.on_state_change = self.quando_midia_terminar
        self.player.on_track_change = self.quando_faixa_muda
        
        self.criar_widgets()
        self.atualizar_relogio()
        
        if self.cidade_salva and self.estado_salvo:
            self.atualizar_temperatura()
        
        self.root.protocol("WM_DELETE_WINDOW", self.fechar)
    
    def criar_widgets(self):
        main_frame = tk.Frame(self.root, bg='#1a1a2e')
        main_frame.pack(fill='both', expand=True, padx=20, pady=20)
        
        tk.Label(main_frame, text="IASD - PQ.VITÓRIA REǴIA", 
                font=("Adventist Sans", 24, "bold"), fg='#F5BE08', bg='#1a1a2e').pack(pady=(10, 5))
        
        self.hora_label = tk.Label(main_frame, text="", font=("Digital-7", 30, "bold"), 
                                   fg="#F5BE08", bg='#1a1a2e')
        self.hora_label.pack(pady=5)
        
        self.temp_label = tk.Label(main_frame, text="", font=("Digital-7", 24, "bold"), 
                                   fg="#F5BE08", bg='#1a1a2e')
        self.temp_label.pack(pady=2)
        
        self.status_label = tk.Label(main_frame, text="", font=("Arial", 14), 
                                     fg='#F5BE08', bg='#1a1a2e')
        self.status_label.pack(pady=5)
        
        cidade_frame = tk.Frame(main_frame, bg='#1a1a2e')
        cidade_frame.pack(pady=2)
        
        tk.Label(cidade_frame, text="📍 Clima:", font=("Arial", 12), 
                fg='#F5BE08', bg='#1a1a2e').pack(side='left', padx=(0, 5))
        
        self.entry_cidade = tk.Entry(cidade_frame, width=15, font=("Arial", 11),
                                      bg='#0f3460', fg='#F5BE08', insertbackground='#F5BE08')
        self.entry_cidade.pack(side='left', padx=2)
        self.entry_cidade.insert(0, "Cidade")
        self.entry_cidade.bind("<FocusIn>", lambda e: self._on_focus_cidade())
        self.entry_cidade.bind("<FocusOut>", lambda e: self._on_focus_out_cidade())
        
        if self.cidade_salva:
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.insert(0, self.cidade_salva)
            self.entry_cidade.config(fg='white')
        
        self.entry_estado = tk.Entry(cidade_frame, width=8, font=("Arial", 11),
                                      bg='#0f3460', fg='#F5BE08', insertbackground='#F5BE08')
        self.entry_estado.pack(side='left', padx=2)
        self.entry_estado.insert(0, "UF")
        self.entry_estado.bind("<FocusIn>", lambda e: self._on_focus_estado())
        self.entry_estado.bind("<FocusOut>", lambda e: self._on_focus_out_estado())
        
        if self.estado_salvo:
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.insert(0, self.estado_salvo)
            self.entry_estado.config(fg='white')
        
        tk.Button(cidade_frame, text="Salvar", font=("Arial", 11, "bold"),
                 bg="#654A8D", fg='#F5BE08', activebackground='#7b2ff7',
                 command=self.salvar_cidade, cursor='hand2').pack(side='left', padx=5)
        
        busca_container = tk.Frame(main_frame, bg='#1a1a2e')
        busca_container.pack(pady=5)
        
        busca_frame = tk.Frame(busca_container, bg='#16213e')
        busca_frame.pack(ipady=8, ipadx=10)
        
        tk.Label(busca_frame, text="🔍", fg='#F5BE08', bg='#16213e', 
                font=("Arial", 16)).pack(side='left', padx=(10, 5))
        
        self.entry_busca = tk.Entry(busca_frame, width=20, font=("Arial", 16),
                                    bg='#0f3460', fg='#F5BE08', insertbackground='#F5BE08',
                                    justify='center')
        self.entry_busca.pack(side='left', padx=5, ipady=5)
        self.entry_busca.insert(0, "Buscar hino...")
        self.entry_busca.bind("<FocusIn>", self._on_focus_in)
        self.entry_busca.bind("<FocusOut>", self._on_focus_out)
        self.entry_busca.bind("<Return>", self.enter_busca)
        self.entry_busca.bind("<KeyRelease>", self.on_busca_digitada)

        self.repetir_var = tk.BooleanVar(value=False)
        self.btn_repetir = tk.Checkbutton(
            busca_frame,
            text="🔁 Repetir",
            variable=self.repetir_var,
            bg='#16213e',
            fg='#F5BE08',
            selectcolor='#0f3460',
            activebackground='#16213e',
            activeforeground='#F5BE08',
            font=("Arial", 11),
            cursor='hand2'
        )
        self.btn_repetir.pack(side='left', padx=(5, 10))
        
        list_container = tk.Frame(main_frame, bg='#16213e')
        list_container.pack(fill='both', expand=True, pady=10)
        
        self.canvas_lista = tk.Canvas(list_container, bg='#16213e', highlightthickness=0)
        scrollbar = tk.Scrollbar(list_container, orient="vertical", command=self.canvas_lista.yview)
        self.scroll_frame = tk.Frame(self.canvas_lista, bg='#16213e')
        
        self.scroll_frame.bind("<Configure>", lambda e: self.canvas_lista.configure(
            scrollregion=self.canvas_lista.bbox("all")))
        
        self.canvas_lista.create_window((0, 0), window=self.scroll_frame, anchor="nw")
        self.canvas_lista.configure(yscrollcommand=scrollbar.set)
        
        self.canvas_lista.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        controls_frame = tk.Frame(main_frame, bg='#16213e')
        controls_frame.pack(fill='x', pady=(10, 0), ipady=10)
        
        botoes = [
            ("⏯ Play/Pause", self.player.play_pause),
            ("⏹ Stop", self.parar),
            ("⏭ Próximo", self.tocar_proximo),
            ("⏮ Anterior", self.tocar_anterior)
        ]
        
        for texto, comando in botoes:
            tk.Button(controls_frame, text=texto, font=("Arial", 12, "bold"),
                     bg='#533483', fg='#F5BE08', activebackground='#7b2ff7',
                     command=comando, cursor='hand2', padx=15, pady=8).pack(
                     side='left', padx=5, expand=True)
    
    def _on_focus_cidade(self):
        if self.entry_cidade.get() == "Cidade":
            self.entry_cidade.delete(0, tk.END)
            self.entry_cidade.config(fg='white')
    
    def _on_focus_out_cidade(self):
        if not self.entry_cidade.get().strip():
            self.entry_cidade.insert(0, "Cidade")
            self.entry_cidade.config(fg='gray')
    
    def _on_focus_estado(self):
        if self.entry_estado.get() == "UF":
            self.entry_estado.delete(0, tk.END)
            self.entry_estado.config(fg='white')
    
    def _on_focus_out_estado(self):
        if not self.entry_estado.get().strip():
            self.entry_estado.insert(0, "UF")
            self.entry_estado.config(fg='gray')
    
    def _on_focus_in(self, event):
        if self.entry_busca.get() == "Buscar hino...":
            self.entry_busca.delete(0, tk.END)
            self.entry_busca.config(fg='#F5BE08')
    
    def _on_focus_out(self, event):
        if not self.entry_busca.get().strip():
            self.entry_busca.insert(0, "Buscar hino...")
            self.entry_busca.config(fg='#F5BE08')
    
    def salvar_cidade(self):
        cidade = self.entry_cidade.get().strip()
        estado = self.entry_estado.get().strip().upper()
        
        if not cidade or cidade == "Cidade" or not estado or estado == "UF":
            self.status_label.config(text="⚠️ Preencha cidade e UF!")
            return
        
        self.config_data["cidade"] = cidade
        self.config_data["estado"] = estado
        self.cidade_salva = cidade
        self.estado_salvo = estado
        
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config_data, f, indent=2)
        
        self.status_label.config(text=f"✅ Local salvo: {cidade}/{estado}")
        self.atualizar_temperatura()
    
    def atualizar_temperatura(self):
        if not self.cidade_salva or not self.estado_salvo:
            return
        
        self.temperatura_atual = obter_temperatura(self.cidade_salva, self.estado_salvo)
        
        if self.temperatura_atual and "Erro" not in self.temperatura_atual and "não encontrada" not in self.temperatura_atual:
            self.temp_label.config(text=f"🌡️ {self.cidade_salva}: {self.temperatura_atual}")
        else:
            self.temp_label.config(text="🌡️ Temperatura indisponível")
            self.temperatura_atual = "--"
        
        self.root.after(1800000, self.atualizar_temperatura)
    
    def quando_faixa_muda(self, indice, arquivo):
        self.arquivo_atual = arquivo
        self.atualizar_status()
        self.atualizar_lista()
    
    def quando_midia_terminar(self, estado):
        if estado == "ended":
            if self.repetir_var.get():
                self.root.after(200, self._repetir_playlist)
            else:
                self.root.after(200, self._tocar_proxima)
    
    def _tocar_proxima(self):
        if not self.player.proximo():
            self.parar()

    def _repetir_playlist(self):
        if not self.arquivos_encontrados:
            if self.arquivo_atual:
                self.tocar_arquivo(self.arquivo_atual)
            return

        if len(self.arquivos_encontrados) == 1:
            self.tocar_arquivo(self.arquivos_encontrados[0])
        else:
            self.player.carregar_playlist(self.arquivos_encontrados)
            self.player.tocar_indice(0)
    
    def carregar_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        return {}
    
    def enter_busca(self, event=None):
        termo = self.entry_busca.get().strip()
        if not termo or termo == "Buscar hino...":
            return
        if not self.busca_realizada:
            self.buscar()
            self.busca_realizada = True
        else:
            arquivos = self.buscar_arquivos_multimidia(termo)
            if arquivos:
                self.tocar_arquivo(arquivos[0])

    def on_busca_digitada(self, event=None):
        termo = self.entry_busca.get().strip()
        if not termo or termo == "Buscar hino...":
            self.arquivos_encontrados = []
            self.player.carregar_playlist([])
            self.atualizar_lista()
            return
        self.buscar()
    
    def reset_busca(self, event=None):
        self.busca_realizada = False
    
    def buscar_arquivos_multimidia(self, termo=""):
        extensoes = [".mp4", ".flv", ".webm", ".mp3", ".mkv", ".wmv"]
        arquivos_encontrados = []
        termo_original = termo.strip()
        termo_lower = termo_original.lower()
        
        for extensao in extensoes:
            padrao = os.path.join(self.pasta_videos, f"**/*{extensao}")
            try:
                todos_arquivos = glob.glob(padrao, recursive=True)
            except:
                continue
            
            for arquivo in todos_arquivos:
                nome_arquivo = os.path.basename(arquivo).lower()
                nome_sem_ext = re.sub(r'\.[^.]+$', '', nome_arquivo)
                nome_normalizado = re.sub(r'(?<=\d)\.(?=\d)', '@@', nome_sem_ext)
                palavras = re.split(r'[\s_\-\.]+', nome_normalizado)
                palavras = [p.replace('@@', '.') for p in palavras]

                if not termo_original:
                    continue

                if termo_original.isdigit():
                    if re.match(rf'^{re.escape(termo_lower)}([\s_\-\.].*)?$', nome_sem_ext):
                        arquivos_encontrados.append(arquivo)
                else:
                    termo_normalizado = re.sub(r'[^a-z0-9]+', ' ', termo_lower).strip()
                    nome_normalizado = re.sub(r'[^a-z0-9]+', ' ', nome_sem_ext).strip()
                    if not termo_normalizado:
                        continue

                    tokens_termo = termo_normalizado.split()
                    tokens_nome = nome_normalizado.split()
                    if len(tokens_termo) == 1:
                        if tokens_termo[0] in tokens_nome:
                            arquivos_encontrados.append(arquivo)
                    else:
                        for i in range(len(tokens_nome) - len(tokens_termo) + 1):
                            if tokens_nome[i:i + len(tokens_termo)] == tokens_termo:
                                arquivos_encontrados.append(arquivo)
                                break
        
        return sorted(list(set(arquivos_encontrados)))
    
    def buscar(self):
        termo = self.entry_busca.get().lower().strip()
        if not termo or termo == "buscar hino...":
            self.arquivos_encontrados = []
            self.player.carregar_playlist([])
            self.atualizar_lista()
            return
        self.arquivos_encontrados = self.buscar_arquivos_multimidia(termo)
        self.player.carregar_playlist(self.arquivos_encontrados)
        if self.arquivo_atual and self.arquivo_atual in self.arquivos_encontrados:
            self.player.index = self.arquivos_encontrados.index(self.arquivo_atual)
        self.atualizar_lista()
    
    def atualizar_lista(self):
        for w in self.scroll_frame.winfo_children():
            w.destroy()
        
        if not self.arquivos_encontrados:
            tk.Label(self.scroll_frame, text="🔍 Nenhum arquivo encontrado", 
                    fg='gray', bg='#16213e', font=("Arial", 12)).pack(pady=20)
            return
        
        tk.Label(self.scroll_frame, text=f"📋 {len(self.arquivos_encontrados)} arquivos", 
                fg='gray', bg='#16213e', font=("Arial", 11)).pack(pady=5)
        
        for i, caminho in enumerate(self.arquivos_encontrados[:]):
            nome = os.path.basename(caminho)
            tipo = "🎵" if caminho.lower().endswith('.mp3') else "🎬"
            prefixo = "▶" if (self.arquivo_atual and caminho == self.arquivo_atual) else " "
            texto = f"{prefixo} {i+1}. {tipo} {nome}"
            
            tk.Button(self.scroll_frame, text=texto, anchor='w',
                     font=("Arial", 11), bg='#0f3460', fg='white',
                     activebackground='#533483',
                     command=lambda c=caminho: self.tocar_arquivo(c)).pack(fill='x', pady=1)
    
    def tocar_arquivo(self, caminho):
        if self.arquivos_encontrados and caminho in self.arquivos_encontrados:
            self.player.carregar_playlist(self.arquivos_encontrados)
            self.player.tocar_indice(self.arquivos_encontrados.index(caminho))
        else:
            self.arquivo_atual = caminho
            self.player.carregar_playlist([caminho])
            self.player.play_pause()
    
    def tocar_proximo(self):
        return self.player.proximo()
    
    def tocar_anterior(self):
        return self.player.anterior()
    
    def atualizar_status(self):
        nome = os.path.basename(self.arquivo_atual) if self.arquivo_atual else ""
        if self.arquivo_atual and self.player.is_playing:
            if self.arquivos_encontrados and self.arquivo_atual in self.arquivos_encontrados:
                pos = self.arquivos_encontrados.index(self.arquivo_atual) + 1
                total = len(self.arquivos_encontrados)
                base_text = f"▶ {nome} ({pos}/{total})"
            else:
                base_text = f"▶ {nome}"
        elif self.player.is_paused:
            base_text = f"⏸️ {nome} (Pausado)"
        else:
            base_text = ""

        if self.player and (self.player.tempo_inicio is not None or self.player.tempo_acumulado > 0) and nome:
            elapsed = self.player.obter_tempo_decorrido()
            total = self.player.duracao_total
            if total:
                base_text = f"{base_text} • ⏱️ {self._formatar_tempo(elapsed)} / {self._formatar_tempo(total)}"
            else:
                base_text = f"{base_text} • ⏱️ {self._formatar_tempo(elapsed)}"

        self.status_label.config(text=base_text)
    
    def parar(self):
        self.player.stop()
        self.arquivo_atual = None
        self.atualizar_status()
        self.atualizar_lista()

    def _formatar_tempo(self, segundos):
        if segundos is None:
            return "00:00"
        segundos = int(segundos)
        minutos, seg = divmod(segundos, 60)
        horas, minutos = divmod(minutos, 60)
        if horas:
            return f"{horas:02d}:{minutos:02d}:{seg:02d}"
        return f"{minutos:02d}:{seg:02d}"
    
    def atualizar_relogio(self):
        try:
            hora_atual = datetime.now().strftime("%H:%M:%S")
            self.hora_label.config(text=hora_atual)
            
            self.atualizar_status()
            if self.player and self.player.telao.mostrando_relogio:
                temp_display = self.temperatura_atual if self.temperatura_atual and "Erro" not in self.temperatura_atual and "não encontrada" not in self.temperatura_atual else ""
                if not temp_display or temp_display == "--":
                    temp_display = ""
                self.player.mostrar_relogio(hora_atual, temp_display)
        except:
            pass
        self.root.after(1000, self.atualizar_relogio)
    
    def run(self):
        def update_telao():
            if self.player and self.player.telao.rodando:
                self.player.telao.update()
                self.root.after(100, update_telao)
        
        update_telao()
        self.root.mainloop()
    
    def fechar(self):
        if self.player:
            self.player.stop()
            self.player.telao.fechar()
        self.root.destroy()


if __name__ == "__main__":
    print("🎵 Hinário Deep - Iniciando...")
    app = AppInterface()
    app.run()