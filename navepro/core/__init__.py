"""

Camada de infraestrutura pura do NavePro:

- ambiente      → detecção de SO / ambiente AppImage
- paths         → caminhos de recursos, dados do usuário, ícones de janela
- ssl_context   → contexto SSL com certificados do sistema e _baixar()
- textos        → utilitários de texto (detecção de mídia, acentos, normalização)
- tema          → cores/elementos dos temas da interface
- atualizacao   → verificação de atualizações no GitHub e download de instalador
"""