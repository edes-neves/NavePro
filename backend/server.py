# backend/server.py
from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
import os
import sys

# Adiciona o diretório atual ao path para importar database.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database

app = Flask(__name__)
CORS(app)

# Pasta onde os arquivos enviados serão salvos
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Extensões permitidas
EXTENSOES_VIDEO = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm'}
EXTENSOES_AUDIO = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
EXTENSOES_TEXTO = {'.txt', '.pdf', '.doc', '.docx', '.md'}


def detectar_tipo(extensao):
    """Detecta o tipo de mídia baseado na extensão."""
    ext = extensao.lower()
    if ext in EXTENSOES_VIDEO:
        return 'video'
    elif ext in EXTENSOES_AUDIO:
        return 'audio'
    elif ext in EXTENSOES_TEXTO:
        return 'texto'
    return None


@app.route('/')
def index():
    """Página inicial - interface web para upload."""
    return render_template('upload.html')


# -------- API REST --------

@app.route('/api/midia', methods=['GET'])
def listar_midia():
    """Lista todas as mídias cadastradas, com filtros opcionais."""
    tipo = request.args.get('tipo')  # video, audio, texto
    busca = request.args.get('busca', '')
    
    resultados = database.listar_midia(tipo=tipo, busca=busca)
    return jsonify(resultados)


@app.route('/api/midia/<int:midia_id>', methods=['GET'])
def obter_midia(midia_id):
    """Retorna os dados de uma mídia específica."""
    midia = database.obter_midia_por_id(midia_id)
    if not midia:
        return jsonify({"erro": "Mídia não encontrada"}), 404
    return jsonify(midia)


@app.route('/api/midia/upload', methods=['POST'])
def upload_midia():
    """Faz upload de um arquivo (vídeo, áudio ou texto)."""
    if 'arquivo' not in request.files:
        return jsonify({"erro": "Nenhum arquivo enviado"}), 400
    
    arquivo = request.files['arquivo']
    if arquivo.filename == '':
        return jsonify({"erro": "Nome do arquivo vazio"}), 400
    
    # Detecta o tipo
    nome_original = arquivo.filename
    extensao = os.path.splitext(nome_original)[1].lower()
    tipo = detectar_tipo(extensao)
    
    if not tipo:
        return jsonify({
            "erro": f"Tipo de arquivo não suportado: {extensao}. "
                    f"Use: Vídeo ({', '.join(EXTENSOES_VIDEO)}), "
                    f"Áudio ({', '.join(EXTENSOES_AUDIO)}) ou "
                    f"Texto ({', '.join(EXTENSOES_TEXTO)})"
        }), 400
    
    # Salva o arquivo
    caminho_completo = os.path.join(UPLOAD_FOLDER, nome_original)
    
    # Evita sobrescrever: se já existe, adiciona um número
    contador = 1
    while os.path.exists(caminho_completo):
        nome_base, ext = os.path.splitext(nome_original)
        caminho_completo = os.path.join(UPLOAD_FOLDER, f"{nome_base}_{contador}{ext}")
        contador += 1
    
    arquivo.save(caminho_completo)
    tamanho = os.path.getsize(caminho_completo)
    
    # Nome de exibição (pode vir do formulário ou usar o nome do arquivo)
    nome_exibicao = request.form.get('nome_exibicao', '')
    if not nome_exibicao:
        nome_exibicao = os.path.splitext(os.path.basename(caminho_completo))[0]
    
    # Mime type
    import mimetypes
    mime_type, _ = mimetypes.guess_type(caminho_completo)
    if not mime_type:
        mime_type = "application/octet-stream"
    
    # Insere no banco
    midia_id = database.inserir_midia(
        nome_original=os.path.basename(caminho_completo),
        nome_exibicao=nome_exibicao,
        tipo=tipo,
        caminho_arquivo=caminho_completo,
        tamanho_bytes=tamanho,
        mime_type=mime_type
    )
    
    return jsonify({
        "mensagem": "✅ Upload realizado com sucesso!",
        "id": midia_id,
        "nome": nome_exibicao,
        "tipo": tipo,
        "tamanho": tamanho
    }), 201


@app.route('/api/midia/<int:midia_id>/download', methods=['GET'])
def download_midia(midia_id):
    """Faz o download do arquivo de mídia."""
    midia = database.obter_midia_por_id(midia_id)
    if not midia:
        return jsonify({"erro": "Mídia não encontrada"}), 404
    
    caminho = midia['caminho_arquivo']
    if not os.path.exists(caminho):
        return jsonify({"erro": "Arquivo não encontrado no disco"}), 404
    
    return send_file(caminho, as_attachment=True)


@app.route('/api/midia/<int:midia_id>', methods=['DELETE'])
def deletar_midia(midia_id):
    """Remove uma mídia (exclusão lógica)."""
    sucesso = database.deletar_midia(midia_id)
    if not sucesso:
        return jsonify({"erro": "Mídia não encontrada"}), 404
    return jsonify({"mensagem": "✅ Mídia removida com sucesso!"})


@app.route('/api/midia/contagem', methods=['GET'])
def contar_midias():
    """Retorna contagem de mídias por tipo."""
    return jsonify(database.contar_midia())


if __name__ == '__main__':
    # Inicializa o banco
    database.init_db()
    
    print("="*50)
    print("🎵 BACKEND DO HINÁRIO - Servidor Iniciado!")
    print(f"📂 Uploads salvos em: {UPLOAD_FOLDER}")
    print(f"🌐 Acesse: http://127.0.0.1:5000")
    print("="*50)
    
    app.run(host='0.0.0.0', port=5000, debug=True)