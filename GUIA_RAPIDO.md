# Guia rápido

1. Abra `ImageMagickStudio.exe` na pasta Aplicativo-2.0/ImageMagickStudio.
2. Clique em **Adicionar arquivos**, **Adicionar pasta** ou arraste arquivos/pastas para a janela. Subpastas são pesquisadas. Selecione uma linha para a prévia.
3. Escolha a operação no seletor acima da tabela. Conversão aplica os ajustes de todas as categorias da barra lateral. PDF, GIF e composição usam a mesma lista na ordem exibida.
4. Configure formato e ajustes. Para recortar com o mouse, marque **Selecionar recorte** e arraste sobre ORIGINAL. Os valores são preenchidos em Recorte.
5. Escolha uma pasta de saída. O padrão de conflitos é renomear; substituir sempre exige confirmação e nunca pode atingir um arquivo da lista original.
6. Clique em **Executar processamento**. **Cancelar** encerra o processo ImageMagick ativo e seus delegates; operações de biblioteca verificam o cancelamento entre páginas/quadros. Arquivos concluídos permanecem na saída.
7. Confira o resumo e os estados. Dê duplo clique em um item para a causa técnica. Exporte JSON/CSV, repita falhas ou abra a pasta de saída.

## Receitas

- **PNG para JPG:** Converter imagens → Conversão: JPG, qualidade 90 → Fundo: cor desejada.
- **Instagram:** Redimensionar: preset Instagram → modo Preencher e recortar → escolher JPG ou PNG.
- **Reduzir sem ampliar:** modo Somente reduzir, largura/altura máximas.
- **PDF com fotos:** Imagens para PDF → ordenar a lista → PDF: A4, margens 10 mm, Ajustar.
- **Mesclar PDFs:** adicionar PDFs → Mesclar PDFs → Saída e lote: nome do arquivo → Executar. Ajustes raster são ignorados.
- **Reordenar PDF:** um PDF → Reordenar / extrair páginas → PDF: `3,1,2` (ou intervalos como `5-1`), ou **Organizar páginas visualmente** e arrastar as miniaturas para a ordem desejada.
- **Extrair páginas:** Dividir PDF por página, campo Páginas `2-5`. Cada página vira um PDF separado. Para um único PDF contendo o intervalo, use Reordenar / extrair páginas.
- **GIF:** adicionar imagens diferentes → Criar GIF animado → largura/altura em Redimensionar → GIF: duração global ou lista `100,200,300`. Cada valor corresponde a uma linha. Execute e use Visualizar GIF selecionado.
- **Grade:** Montar grade → Composição: colunas, espaçamento, cor do canvas → formato PNG. Canvas aceita `transparent`.

Atalhos: **Ctrl+O** adicionar, **Delete** remover seleção, **Ctrl+Enter** executar, **Escape** cancelar. Prévia: roda do mouse amplia, arraste para navegar; Ajustar e 100% alteram o zoom da imagem de prévia.

Preferências: registro do Windows em `HKEY_CURRENT_USER/Software/ImageMagickStudio/Studio2`. Logs: `%APPDATA%/ImageMagickStudio/studio.log`, com rotação para limitar espaço.
