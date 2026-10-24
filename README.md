# ImageMagick Studio 2.0

Aplicativo desktop para Windows, refeito em Python e PySide6, com interface em português. A implementação antiga foi preservada na pasta superior; esta pasta contém a nova aplicação independente.

## Executar

A versão pronta fica em `../Aplicativo-2.0/ImageMagickStudio/ImageMagickStudio.exe`. Mantenha a pasta `_internal` ao lado do executável. Não é necessário instalar Python para essa versão.

Instale o **ImageMagick 7 de 64 bits**, incluindo os codecs desejados e a opção de adicionar ao PATH. O programa procura `magick.exe`, nunca o `convert.exe` do Windows. Um caminho manual pode ser salvo em **Diagnóstico**. O ImageMagick e seus delegates não são redistribuídos com o aplicativo.

Para desenvolvimento (Python 3.12 a 3.14 de 64 bits):

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python run.py
```

Nesta estação as dependências PDF e testes também foram colocadas em `vendor/`; `run.py` detecta essa pasta. Ela é uma conveniência local e não faz parte do código-fonte.

## Recursos

- Conversão individual/lote, qualidade, ícones multirresolução e formatos detectados dinamicamente.
- Oito modos de dimensões, recorte numérico, proporções e seleção visual.
- EXIF, rotação livre, espelhamento, cor, luz e treze filtros.
- Remoção de fundo por cor, transparência, fundo e aparagem.
- Marca-d’água textual ou de imagem, posição e opacidade.
- Remoção de metadados com preservação opcional de ICC e aviso de GPS.
- Imagens para PDF com página, ajuste e margens; renderização, divisão, extração, reordenação e mesclagem de PDFs sem rasterizar o texto.
- GIF animado com ordem, duração global/individual, repetição e normalização; extração de quadros e reprodução do resultado.
- Composição horizontal, vertical, grade e sobreposição.
- Arquivos/pastas por arrastar e soltar, reordenação, lista de estados, paralelismo, cancelamento de processos, resumo e relatórios JSON/CSV.
- Interface assíncrona, comparativo lado a lado, zoom, preferências e logs rotativos.

Leia [GUIA_RAPIDO.md](GUIA_RAPIDO.md) e [LIMITACOES.md](LIMITACOES.md) antes de usar formatos especiais.

## Arquitetura e pipeline

```text
run.py                    entrada de desenvolvimento e build
studio/app.py             inicialização e logs
studio/domain.py          opções, resultados, cancelamento e páginas
studio/infrastructure.py  ImageMagick, caminhos e gravação atômica
studio/pipeline.py        única montagem de transformações raster
studio/services.py        fila, PDFs, GIFs, composição e relatório
studio/ui.py              interface e workers Qt
scripts/                  testes e empacotamento
tests/                    fixtures pequenas geradas durante os testes
```

A inspeção do legado encontrou uma interface CustomTkinter com abas, conversores duplicados e detecção que tentava `convert`. Nenhum módulo antigo foi reutilizado. A nova separação mantém a montagem de comandos em um único lugar; PDF e composição possuem serviços próprios, sem classes intermediárias desnecessárias.

Ordem raster: validar arquivo → orientar EXIF → primeiro quadro → recortar → redimensionar → girar/espelhar → cor/luz → efeito → transparência/aparagem → marca-d’água → achatar fundo quando necessário → metadados/ICC → codificar → verificar dimensões → publicar saída. A gravação ocorre em temporário na pasta de destino e só então o arquivo é renomeado. Os originais são protegidos mesmo quando “substituir” é escolhido.

Em operações conjuntas, essa pipeline é aplicada aos arquivos de entrada; a montagem ocorre depois. PDFs de mesclagem/divisão/reordenação usam pypdf e ignoram os ajustes raster. PDF para imagens renderiza primeiro com PyMuPDF. Imagens para PDF aplicam os ajustes antes de inserir as imagens nas páginas.

## Testes e build

```powershell
python scripts/test.py
python scripts/build.py
```

O build gera um aplicativo em pasta (PyInstaller `onedir`) em `../Aplicativo-2.0/`. Não é um instalador MSI. Distribua essa pasta inteira, opcionalmente compactada. Não mova apenas o `.exe`. A versão de Python, arquitetura e dependências devem coincidir para reproduzir o build.

O script verifica a biblioteca ICU coletada pelo PyInstaller. Caso uma instalação externa no PATH forneça uma ICU incompatível, ela é removida do pacote para que o Qt utilize a ICU do próprio Windows. Essa situação foi encontrada e corrigida durante o teste real do executável.

O teste real do executável pode ser executado por `ImageMagickStudio.exe --smoke-test CAMINHO_NOVO`, que cria imagens sintéticas, converte uma delas e grava `smoke-result.json` na pasta indicada, sem abrir janelas. O modo usa as dependências incluídas no executável.

## Dependências e licenças

ImageMagick: <https://imagemagick.org/script/download.php#windows>. Ghostscript: <https://ghostscript.com/releases/gsdnld.html>. Ghostscript é necessário para certos caminhos EPS/PS do ImageMagick; PDFs comuns usam PyMuPDF/pypdf. A instalação deve vir das fontes oficiais. O painel Diagnóstico apresenta versão, formatos e delegates reais.

O projeto utiliza PySide6 (LGPL/comercial), Pillow, pypdf, PyMuPDF (AGPL/comercial) e ImageMagick. Revise os termos aplicáveis antes de redistribuir, sobretudo para uma distribuição proprietária com PyMuPDF/Ghostscript. A documentação solicitou essas bibliotecas explicitamente. Nenhuma licença do código deste projeto foi presumida ou criada.

Referências de implementação: [opções oficiais do ImageMagick](https://imagemagick.org/command-line-options/) e [mesclagem com pypdf](https://pypdf.readthedocs.io/en/latest/user/merging-pdfs.html).
