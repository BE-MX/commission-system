import { workbenchUrl } from '@/lib/workbench-url';
import { writePsd, type Layer, type Psd } from 'ag-psd';
import type { Selection, StockColor, TemplateSummary } from '@/lib/catalog';
import { activeColorsFor, layoutFor, sizeText } from '@/lib/poster';
import {
  createInventoryOverlayPlan,
  drawInventoryOverlayPlan,
  type InventoryStatusMap,
} from '@/lib/inventory-overlay';

function canvas(width: number, height: number) {
  const value = document.createElement('canvas');
  value.width = Math.max(1, Math.round(width));
  value.height = Math.max(1, Math.round(height));
  return value;
}

async function loadImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`无法读取源文件素材：${src}`));
    image.src = workbenchUrl(src);
  });
}

function textLayer(
  name: string,
  text: string,
  left: number,
  top: number,
  width: number,
  fontSize: number,
): Layer {
  const layerCanvas = canvas(width, fontSize + 12);
  const context = layerCanvas.getContext('2d');
  if (!context) throw new Error('当前浏览器无法创建文字图层。');
  context.fillStyle = '#050505';
  context.font = `${fontSize}px Arial`;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(text, width / 2, layerCanvas.height / 2);

  return {
    name,
    left: Math.round(left),
    top: Math.round(top),
    canvas: layerCanvas,
    text: {
      text,
      transform: [
        1,
        0,
        0,
        1,
        Math.round(left + width / 2),
        Math.round(top + fontSize),
      ],
      style: {
        font: { name: 'ArialMT' },
        fontSize,
        fillColor: { r: 5, g: 5, b: 5 },
      },
      paragraphStyle: { justification: 'center' },
    },
  };
}

export async function createLayeredPsd(
  colors: StockColor[],
  item: TemplateSummary,
  selection: Selection,
  composite: HTMLCanvasElement,
  inventory?: InventoryStatusMap,
) {
  const active = activeColorsFor(colors, item, selection);
  const slots = layoutFor(item, active);
  if (slots.length !== active.length)
    throw new Error('当前颜色数量无法生成 PSD。');
  const needsHot = active.some(({ entry }) => entry.hot);
  const [base, hot, ...photos] = await Promise.all([
    loadImage(item.baseUrl),
    needsHot ? loadImage(item.hotUrl ?? '/api/runtime-assets/hot.png') : Promise.resolve(null),
    ...active.map(({ color }) => loadImage(color.image)),
  ]);
  const baseCanvas = canvas(item.width, item.height);
  baseCanvas.getContext('2d')?.drawImage(base, 0, 0, item.width, item.height);

  const colorGroups: Layer[] = active.map(({ color, entry }, index) => {
    const slot = slots[index];
    const photoCanvas = canvas(slot.size, slot.size);
    const photoContext = photoCanvas.getContext('2d');
    if (!photoContext) throw new Error('当前浏览器无法创建色块图层。');
    photoContext.drawImage(photos[index], 0, 0, slot.size, slot.size);
    photoContext.strokeStyle = '#e2bd30';
    photoContext.strokeRect(0.5, 0.5, slot.size - 1, slot.size - 1);
    const codeTop = slot.codeY - (slot.codeSize + 12) / 2;
    const sizeTop = slot.lengthY - (slot.lengthSize + 12) / 2;
    const children: Layer[] = [];
    const inventoryPlan = createInventoryOverlayPlan(slot, entry, inventory);
    if (inventoryPlan.bounds) {
      const { x, y, width, height } = inventoryPlan.bounds;
      const inventoryCanvas = canvas(width, height);
      const inventoryContext = inventoryCanvas.getContext('2d');
      if (!inventoryContext)
        throw new Error('当前浏览器无法创建库存提示图层。');
      inventoryContext.translate(-x, -y);
      drawInventoryOverlayPlan(inventoryContext, inventoryPlan);
      children.push({
        name: '库存提示（英文）',
        left: x,
        top: y,
        canvas: inventoryCanvas,
      });
    }
    if (entry.hot && hot) {
      const width = slot.size >= 240 ? 65 : 47;
      const hotCanvas = canvas(width, (width * hot.height) / hot.width);
      hotCanvas
        .getContext('2d')
        ?.drawImage(hot, 0, 0, hotCanvas.width, hotCanvas.height);
      children.push({
        name: 'Hot 标记',
        left: Math.round(slot.x + slot.size - width * 0.55),
        top: Math.round(slot.y - 8),
        canvas: hotCanvas,
      });
    }
    children.push(
      textLayer(
        '尺寸（可编辑）',
        sizeText(entry.lengths),
        slot.x - 10,
        sizeTop,
        slot.size + 20,
        slot.lengthSize,
      ),
      textLayer(
        '色号（可编辑）',
        color.code,
        slot.x - 10,
        codeTop,
        slot.size + 20,
        slot.codeSize,
      ),
      {
        name: '色块图（可替换）',
        left: Math.round(slot.x),
        top: Math.round(slot.y),
        canvas: photoCanvas,
      },
    );
    const section = item.sections.find(
      (value) => value.key === entry.section,
    )?.label;
    return {
      name: section ? `${color.code} · ${section}` : color.code,
      opened: false,
      children,
    };
  });

  const compositeCanvas = canvas(item.width, item.height);
  compositeCanvas
    .getContext('2d')
    ?.drawImage(composite, 0, 0, item.width, item.height);
  const psd: Psd = {
    width: item.width,
    height: item.height,
    canvas: compositeCanvas,
    children: [
      { name: '可编辑颜色与尺寸', opened: true, children: colorGroups },
      { name: '固定模板背景', canvas: baseCanvas },
    ],
  };
  const buffer = writePsd(psd, {
    generateThumbnail: true,
    invalidateTextLayers: true,
    noBackground: true,
    compress: false,
  });
  return new Blob([buffer], { type: 'image/vnd.adobe.photoshop' });
}
