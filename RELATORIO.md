# Relatório de entrega — ImageMagick Studio 2.0

Data: 24 de outubro de 2026.

## Entregas

- Aplicativo Windows: `../Aplicativo-2.0/ImageMagickStudio/ImageMagickStudio.exe`, acompanhado por `_internal`.
- Atalho de execução: `../ABRIR_STUDIO_2.0.bat`.
- Fontes nesta pasta, organizadas em `studio/`, `scripts/`, `tests/` e `assets/`.
- Código-fonte compactado: `../ImageMagickStudio-codigo-fonte.zip`.
- README, guia rápido, limitações e changelog. Nenhuma licença de propriedade do usuário foi presumida.
- Captura revisada da interface: `assets/interface.png`.

O projeto antigo, seu executável e seus módulos foram mantidos. A nova implementação não importa os conversores antigos.

## Funcionalidades implementadas

Conversão raster e em lote com codecs detectados, qualidade e ICO multirresolução; preservação opcional de quadros em GIF/WEBP/TIFF; redimensionamento e presets editáveis; recorte com coordenadas, proporções e seleção visual; orientação EXIF, rotação e espelhamento; cor e luz; treze filtros; transparência, remoção de fundo por cor, aparagem, marcas-d’água; metadados e ICC.

PDF: gerar documentos com página, orientação, margens e ajuste; renderizar páginas; mesclar preservando texto; dividir por página, extrair intervalos e reordenar por sequência ou miniaturas arrastáveis. GIF: criação, duração global/individual, repetição, normalização, otimização, extração e reprodução. Composição: horizontal, vertical, grade e sobreposição.

Interface: tema escuro, navegação lateral, arquivos e pastas por arrastar e soltar, leitura de informações em worker, ordenação, remoção, prévia lado a lado, zoom, preferências, diagnóstico e atalhos. Fila: até oito arquivos simultâneos, estados individuais, cancelamento, resumo, exportação JSON/CSV e repetição de falhas.

## Evidências de validação

Suite final: **64 testes aprovados e 2 ignorados**, sem falhas. Os ignorados são HEIC e HEIF, pois o ImageMagick instalado não anuncia codificador para esses formatos. As opções correspondentes ficam desabilitadas.

Os testes usam arquivos pequenos gerados automaticamente e cobrem:

- Todos os modos de dimensões, redução sem ampliação, proporções e recorte.
- Caminhos com espaços, acentos e caracteres chineses; montagem de argumentos.
- Arquivos ausentes/corrompidos, segurança de nomes, colisões e proteção do original.
- Rotação, orientação EXIF, espelhamento, transparência, fundo, remoção por cor e filtros.
- Metadados, perfil ICC, remoção de comentários e preservação de quadros/páginas.
- Mesclagem PDF com texto verificável, extração/divisão/reordenação e renderização.
- GIF com duração/quadros verificáveis e composição nos quatro modos.
- Cancelamento prévio e de processo ativo; temporários descartados em falha.
- Falhas individuais no resumo e relatórios JSON/CSV; ausência de ImageMagick.
- Limite de pixels antes de ampliação excessiva.
- Inicialização da interface e processamento assíncrono com o event loop ativo.

O executável PyInstaller passou por um autoteste de conversão WebP, PDF, GIF animado e grade. A interface empacotada também foi iniciada e capturada pelo modo de teste, verificando categorias e controles. Esses modos criam somente dados sintéticos em uma pasta nova indicada na linha de comando.

A interface foi validada tanto com renderização fora da tela quanto com o backend nativo do Windows. Foram verificadas 13 categorias e 76 controles. Evidências compactas estão em `validacao/`. Durante o teste foi corrigida uma coleta indevida de ICU de um programa externo no PATH; o script de build aplica essa correção automaticamente.

## Ambiente

Windows 11 de 64 bits, Python 3.14.3, PySide6 6.11.1, Pillow 12.1.1, pypdf 6.21.2, PyMuPDF 1.26.7, pytest 9.1.1 e PyInstaller 6.19.0. ImageMagick externo 7.1.2-26 Q16-HDRI; Ghostscript encontrado na máquina.

## Execução e build

Para usar: abra o atalho `ABRIR_STUDIO_2.0.bat` na pasta superior, ou o executável na pasta Aplicativo-2.0. Mantenha `_internal` junto dele. ImageMagick deve estar instalado; configure um caminho manual em Diagnóstico se necessário.

Para desenvolver: crie um ambiente virtual, instale `requirements-dev.txt`, execute `python run.py`. Para validar: `python scripts/test.py`. Para empacotar: `python scripts/build.py`. O resultado é uma pasta de aplicativo; não há instalador MSI ou assinatura digital.

## Diferenças em relação à especificação completa

A implementação é funcional, mas não corresponde integralmente a todas as variações descritas no documento de origem. A prévia compara imagens lado a lado, sem slider; mostra o primeiro quadro e processa a entrada original antes de reduzir a exibição. O botão 100% usa os pixels da prévia. Operações conjuntas são visualizadas no resultado exportado. Há um efeito artístico por execução, e seus parâmetros são compartilhados; alguns efeitos possuem parâmetros fixos indicados na documentação. A duração individual do GIF usa uma lista numérica, sem linha do tempo visual. O progresso de cada arquivo indica fases, e o total conta itens terminados.

O PDF é dividido por página ou extraído em um documento pela ordem/intervalo informados. O organizador visual suporta até 500 páginas. Não há garantia de preservar assinaturas digitais ou toda estrutura interativa de PDFs. Não houve teste em Windows 10 nem em máquina sem as dependências externas. O cancelamento de bibliotecas responde entre páginas/quadros. O pacote gerado é um aplicativo em pasta, sem instalador automático.

Veja `LIMITACOES.md` para os detalhes por formato e as fronteiras da validação. Não há botões reservados a recursos futuros na interface.
