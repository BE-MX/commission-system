// Copyright (c) 2026 Kubai087. Licensed under the Kubai Icons License; see LICENSE.
// The icon set. Each entry: svg(u) builds the layers, target(hover, state) returns the
// numbers for rest or hover, draw(p, E) writes the interpolated numbers back. A contributed
// icon also names its designer's GitHub handle in `by`.
// Ark: the subset of icons the platform uses (upstream examples plus 货车 / 色卡 / 机器人,
// drawn for Ark with the same rules), as an ES module. Entries keep the upstream format.
import {
  KR, CR, f, R, rp, rr, circ, poly, lines, star, gear, cross, arc, cloud, frontPiece, sector, at, CLOCK_MINUTES
} from './engine.js';

// ---------- Icons ----------
// Fills: u.lo(h) / u.up(h) carry the thin bottom band. Use them only on a flat-bottomed
// rectangle of height h whose bottom is clear: nothing within about 3 units of the edge
// and the piece itself not short. Everything else, and curved shapes, use u.loS / u.upS.
// Marks: on a mid-tone (back) body they are white; on a light (front) body or white
// content they take the deep tint; a supporting object laid over the subject (the
// lens) is deep so it reads as separate. Weights: content lines 1.6, glyphs 2.2.
const OL = 'class="ol" data-t="stroke:#5393FF"';
const LINE = 'class="ln" data-t="stroke:#D3E2FC"';
const ACC = 'class="ln" data-t="stroke:#5393FF"';
const DEEP = 'data-t="fill:#2F6FE0"';
const DEEPS = 'data-t="stroke:#2F6FE0"';
const FOLDER_BACK_R = [KR, 1.4, 1.4, KR, KR, KR];
// Keylines (fills; outside strokes add 1 all round), all centred on (15.5, 12.5) and scaled from the folder's 23-wide body
// (Material's 20 / 18 / 20×16 grid × 1.15): circle Ø23, square 20.6, landscape 23×18.4,
// portrait 18.4×23. Outlines sit 1 unit outside a shape; a coloured band around white
// content keeps 2+ units or is dropped so the content meets the edge.
const TRASH_LID = rp([[5.4, 6.6], [5.4, 4], [12.4, 4], [12.4, 1.6], [18.6, 1.6], [18.6, 4], [25.6, 4], [25.6, 6.6]], [1, 1, 0.5, 0.8, 0.8, 0.5, 1, 1]);
const GEAR = gear(6, 11.4, 9);
  const MAIL_T = 3.3;

// A capsule ring centred on the origin: outer w×h, wall t (fill-rule evenodd).
const capsuleRing = (w, h, t) => rr(-w / 2, -h / 2, w, h, h / 2) + rr(-w / 2 + t, -h / 2 + t, w - 2 * t, h - 2 * t, (h - 2 * t) / 2);
const LINK_RING = capsuleRing(15.6, 9.6, 2.8);
// An arc of radius r round the origin from angle a0 to a1 (degrees, clockwise), and a
// solid arrowhead whose base covers the arc's end. Strokes never overlap one another,
// so the head stays crisp instead of clotting where strokes would cross.
function arcArrow(a0, a1, r) {
  const rad = (d) => d * Math.PI / 180;
  const pt = (a) => [r * Math.cos(rad(a)), r * Math.sin(rad(a))];
  const s = pt(a0), e = pt(a1);
  const t = [-Math.sin(rad(a1)), Math.cos(rad(a1))], n = [Math.cos(rad(a1)), Math.sin(rad(a1))];
  const tip = [e[0] + t[0] * 3, e[1] + t[1] * 3];
  const head = rp([[e[0] + n[0] * 2.5, e[1] + n[1] * 2.5], tip, [e[0] - n[0] * 2.5, e[1] - n[1] * 2.5]], 0.5);
  return { arc: `M${f(s[0])} ${f(s[1])}A${r} ${r} 0 0 1 ${f(e[0])} ${f(e[1])}`, head };
}
// Each arrow's tip stops well short of the other arc's tail.
const SYNC_A = arcArrow(215, 300, 4.4), SYNC_B = arcArrow(35, 120, 4.4);
const SHORTCUT_TILES = [[7.2, 4.2], [16.5, 4.2], [7.2, 13.5], [16.5, 13.5]];

export const ICONS = [
  {
    name: '主页',
    // The new-tab home: a house whose door swings open on hover.
    svg: (u) => {
      const roof = rp([[3.6, 12.6], [15.5, 2.4], [27.4, 12.6]], [1.4, 2.2, 1.4]);
      const door = rp(R(13.2, 15.6, 4.6, 7.4), [1.2, 1.2, 0, 0]);
      return `
      <g filter="${u.sh}"><g filter="${u.hi}"><path d="${rr(7.4, 10.6, 16.2, 12.4, KR)}" fill="${u.loS}"/></g></g>
      <path d="${rr(7.4, 10.6, 16.2, 12.4, KR)}" ${OL}/>
      <path d="${door}" fill="${u.pure('#2F6FE0')}"/>
      <g data-n="door"><path d="${door}" fill="#fff"/></g>
      <g filter="${u.hi}"><path d="${roof}" fill="${u.upS}"/></g>
      <path d="${roof}" ${OL}/>`;
    },
    target: (h) => ({ door: h ? 0.3 : 1 }),
    draw(p, E) {
      at(E.door, { transform: `translate(13.2 0) scale(${f(Math.max(0.001, p.door))} 1) translate(-13.2 0)` });
    }
  },
  {
    name: '通知',
    // A bell that swings from its knob; the clapper lags behind.
    svg: (u) => {
      const bell = 'M7.8 18.4C9 17 9.3 15 9.3 12C9.3 8 12 5.2 15.5 5.2C19 5.2 21.7 8 21.7 12C21.7 15 22 17 23.2 18.4Z';
      const rim = rr(5.6, 17.4, 19.8, 3.8, 1.9);
      return `<g data-n="bell">
        <circle cx="15.5" cy="4.4" r="1.8" ${DEEP}/>
        <circle data-n="clap" cx="15.5" cy="21.4" r="2.3" ${DEEP}/>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${bell}" fill="${u.loS}"/></g></g><path d="${bell}" ${OL}/>
        <g filter="${u.hi}"><path d="${rim}" fill="${u.upS}"/></g><path d="${rim}" ${OL}/>
      </g>`;
    },
    target: (h) => ({ swing: h ? 14 : 0, clap: h ? -1.6 : 0 }),
    draw(p, E) {
      at(E.bell, { transform: `rotate(${f(p.swing)} 15.5 4.4)` });
      at(E.clap, { cx: f(15.5 + p.clap) });
    }
  },
  {
    name: '机器人',
    // A robot head with a screen face and an antenna. On hover it blinks and looks up, the
    // antenna springing side to side before it settles upright.
    svg: (u) => {
      const head = rr(5.2, 7.6, 20.6, 15.2, KR), ball = circ(15.5, 3, 1.8);
      return `<g data-n="stem"><path d="M15.5 6.8V4.4" fill="none" stroke-width="1.6" stroke-linecap="round" ${DEEPS}/></g>
        <g filter="${u.sh}"><g filter="${u.hi}"><g data-n="ball"><path d="${ball}" fill="${u.upS}"/></g></g></g>
        <g data-n="ballO"><path d="${ball}" ${OL}/></g>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${head}" fill="${u.loS}"/></g></g><path d="${head}" ${OL}/>
        <path d="${rr(7.6, 10, 15.8, 10.4, CR)}" fill="#fff"/>
        <ellipse data-n="eyeL" cx="12.2" rx="1.6" ${DEEP}/><ellipse data-n="eyeR" cx="18.8" rx="1.6" ${DEEP}/>`;
    },
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      const t = { transform: `rotate(${f(18 * (1 - o) * Math.sin(3 * Math.PI * o))} 15.5 7.6)` };
      at(E.stem, t); at(E.ball, t); at(E.ballO, t);
      const ry = 2 * (1 - 0.75 * Math.sin(Math.PI * o)), cy = 15.2 - 0.6 * o;
      at(E.eyeL, { cy: f(cy), ry: f(ry) }); at(E.eyeR, { cy: f(cy), ry: f(ry) });
    }
  },
  {
    name: '购物车',
    // A cart; on hover a parcel drops into its basket.
    svg: (u) => {
      const basket = rp([[7, 7], [26.8, 7], [24.6, 16.8], [9.4, 16.8]], [1.4, 1.4, 1.8, 1.8]);
      const box = rr(0, 0, 7.4, 6, 1.2);
      return `<path d="M3.4 3.6H6L9.2 16.8H23" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" ${DEEPS}/>
        <g data-n="box"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${box}" fill="${u.upS}"/></g></g><path d="${box}" ${OL}/></g>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${basket}" fill="${u.loS}"/></g></g><path d="${basket}" ${OL}/>
        <circle cx="11.4" cy="20.8" r="2" ${DEEP}/><circle cx="21.6" cy="20.8" r="2" ${DEEP}/>`;
    },
    target: (h) => ({ box: h ? [13.6, 3.2, 1] : [13.6, -1.2, 0] }),
    draw(p, E) { at(E.box, { transform: `translate(${f(p.box[0])} ${f(p.box[1])})`, opacity: f(p.box[2]) }); }
  },
  {
    name: '用户',
    // An avatar in a round frame; on hover the person looks up.
    svg: (u) => {
      const disc = circ(15.5, 12.5, 11.5);
      return `<clipPath id="${u.id('av')}"><path d="${disc}"/></clipPath>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${disc}" fill="${u.loS}"/></g></g>
        <g clip-path="url(#${u.id('av')})">
          <path data-n="body" d="${rp([[5, 27], [5, 22], [10.4, 17.4], [20.6, 17.4], [26, 22], [26, 27]], [0, 0, 4, 4, 0, 0])}" fill="#fff"/>
        </g>
        <circle data-n="head" cx="15.5" cy="10.4" r="4.4" fill="#fff"/>
        <path d="${disc}" ${OL}/>`;
    },
    target: (h) => ({ lift: h ? -1.2 : 0 }),
    draw(p, E) {
      at(E.head, { cy: f(10.4 + p.lift) });
      at(E.body, { transform: `translate(0 ${f(p.lift * 0.4)})` });
    }
  },
  {
    name: '地球',
    // A globe whose meridian swings round as if it turns.
    svg: (u) => {
      const disc = circ(15.5, 12.5, 11.5);
      return `<clipPath id="${u.id('gl')}"><path d="${disc}"/></clipPath>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${disc}" fill="${u.loS}"/></g></g>
        <g clip-path="url(#${u.id('gl')})" fill="none" stroke-width="1.6" stroke="#fff" data-w="stroke">
          <path d="M3 12.5H28"/><path data-n="mer"/>
        </g>
        <path d="${disc}" ${OL}/>`;
    },
    target: (h) => ({ rx: h ? 8.6 : 4.6 }),
    draw(p, E) {
      const rx = p.rx;
      at(E.mer, { d: `M${f(15.5 - rx)} 12.5A${f(rx)} 11.5 0 1 0 ${f(15.5 + rx)} 12.5A${f(rx)} 11.5 0 1 0 ${f(15.5 - rx)} 12.5Z` });
    }
  },
  {
    name: '聊天',
    // Two speech bubbles; the reply in front starts typing on hover.
    svg: (u) => {
      const back = rr(4, 3.3, 16, 11.6, KR);
      const front = rp([[10.2, 8.8], [27, 8.8], [27, 19], [17.4, 19], [13.8, 22.6], [13.8, 19], [10.2, 19]], [KR, KR, KR, 0.5, 0.6, 0.5, KR]);
      return `<g data-n="b"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${back}" fill="${u.loS}"/></g></g><path d="${back}" ${OL}/>
          <path d="${lines(7, 6.8, [6.4])}" class="ln" stroke="#fff" data-w="stroke"/></g>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${front}" fill="${u.upS}"/></g></g><path d="${front}" ${OL}/>
        <circle data-n="d1" cx="14.6" r="1.4" ${DEEP}/><circle data-n="d2" cx="18.6" r="1.4" ${DEEP}/><circle data-n="d3" cx="22.6" r="1.4" ${DEEP}/>`;
    },
    target: (h) => ({ d: h ? [-0.6, -1.5, -0.6] : [0, 0, 0], b: h ? -0.8 : 0 }),
    draw(p, E) {
      at(E.d1, { cy: f(13.9 + p.d[0]) }); at(E.d2, { cy: f(13.9 + p.d[1]) }); at(E.d3, { cy: f(13.9 + p.d[2]) });
      at(E.b, { transform: `translate(${f(p.b)} ${f(p.b)})` });
    }
  },
  {
    name: '剪贴板',
    // A clipboard; a check gets ticked on its sheet on hover.
    svg: (u) => {
      const board = rr(6.3, 2.6, 18.4, 21.2, KR), clip = rp(R(11, 0.8, 9, 4.6), [1.6, 1.6, 1.2, 1.2]);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${board}" fill="${u.loS}"/></g></g><path d="${board}" ${OL}/>
        <path d="${rr(8.6, 6.6, 13.8, 15, CR)}" fill="#fff"/>
        <path d="${lines(11, 10.2, [9])}" ${LINE}/>
        <path data-n="chk" d="M12.2 16.2L14.6 18.6L19 14" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" ${DEEPS}/>
        <g filter="${u.hi}"><path d="${clip}" fill="${u.upS}"/></g><path d="${clip}" ${OL}/>`;
    },
    target: (h) => ({ chk: h ? 1 : 0 }),
    draw(p, E) {
      const L = 9.8;
      at(E.chk, { 'stroke-dasharray': L, 'stroke-dashoffset': f(L * (1 - Math.max(0, Math.min(1, p.chk)))) });
    }
  },
  {
    name: '耳机',
    // Headphones whose cups press in on hover.
    svg: (u) => {
      const band = 'M4.4 14.4A11.1 11.1 0 0 1 26.6 14.4H24A8.5 8.5 0 0 0 7 14.4Z';
      const cup = rr(0, 0, 6.8, 10.6, 3);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${band}" fill="${u.loS}"/></g></g><path d="${band}" ${OL}/>
        <g data-n="l"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${cup}" fill="${u.upS}"/></g></g><path d="${cup}" ${OL}/></g>
        <g data-n="r"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${cup}" fill="${u.upS}"/></g></g><path d="${cup}" ${OL}/></g>`;
    },
    target: (h) => ({ d: h ? 0.8 : 0 }),
    draw(p, E) {
      at(E.l, { transform: `translate(${f(3.6 + p.d)} 12.6)` });
      at(E.r, { transform: `translate(${f(20.6 - p.d)} 12.6)` });
    }
  },
  {
    name: '旗帜',
    // A flag that ripples on hover.
    svg: (u) => `<path d="M8.2 2.4V23.6" fill="none" stroke-width="2.2" stroke-linecap="round" ${DEEPS}/>
      <g filter="${u.sh}"><g filter="${u.hi}"><path data-n="cl" fill="${u.loS}"/></g></g><path data-n="clO" ${OL}/>`,
    target: (h) => ({ a: h ? -2 : 2 }),
    draw(p, E) {
      const a = p.a;
      const d = `M9.2 3.4C13.6 ${f(3.4 - a)} 18 ${f(3.4 + a)} 25 3.4V15.2C18 ${f(15.2 + a)} 13.6 ${f(15.2 - a)} 9.2 15.2Z`;
      at(E.cl, { d }); at(E.clO, { d });
    }
  },
  {
    name: '钱包',
    // A wallet; the card tucked in it rises on hover.
    svg: (u) => {
      const body = rr(4, 5.6, 23, 16.1, KR), pocket = rp(R(4, 11, 23, 10.7), [1.6, 1.6, KR, KR]), card = rr(0, 0, 15, 9, 1.4);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${body}" fill="${u.loS}"/></g></g><path d="${body}" ${OL}/>
        <g data-n="card"><g filter="${u.hi}"><path d="${card}" fill="${u.upS}"/></g><path d="${card}" ${OL}/><path d="${lines(2.2, 2.6, [5.6])}" class="ln" ${DEEPS}/></g>
        <g filter="${u.hi}"><path d="${pocket}" fill="${u.up(10.7)}"/></g><path d="${pocket}" ${OL}/>
        <path d="${rr(19.4, 13.6, 7.6, 4.8, 2.4)}" fill="${u.loS}"/><path d="${rr(19.4, 13.6, 7.6, 4.8, 2.4)}" ${OL}/>`;
    },
    target: (h) => ({ y: h ? 2.4 : 4.6 }),
    draw(p, E) { at(E.card, { transform: `translate(6.6 ${f(p.y)})` }); }
  },
  {
    name: '计算器',
    // A calculator with a display and four operator keys. On hover the equals key is
    // pressed, lights up, and the display fills with the result.
    svg: (u) => {
      const body = rr(6.3, 1, 18.4, 23, KR), eq = rr(16.5, 16.8, 6.2, 5.2, CR);
      const eqMark = 'M18.3 18.1H20.9M18.3 20.7H20.9';
      return `
      <g filter="${u.sh}"><g filter="${u.hi}"><path d="${body}" fill="${u.loS}"/></g></g>
      <path d="${body}" ${OL}/>
      <path d="${rr(8.3, 3, 14.4, 4.6, CR)}" fill="#fff"/>
      <path data-n="read" class="ln" ${DEEPS}/>
      <path d="${rr(8.3, 9.6, 6.2, 5.2, CR) + rr(16.5, 9.6, 6.2, 5.2, CR) + rr(8.3, 16.8, 6.2, 5.2, CR)}" fill="#fff"/>
      <path d="M10.1 12.2H12.7M11.4 10.9V13.5M18.3 12.2H20.9M10.4 18.4L12.4 20.4M12.4 18.4L10.4 20.4" class="ln" ${DEEPS}/>
      <g data-n="eq"><path d="${eq}" fill="#fff"/><path data-n="lit" d="${eq}" fill="${u.pure('#2F6FE0')}"/>
        <path data-n="eqD" d="${eqMark}" class="ln" ${DEEPS}/><path data-n="eqW" d="${eqMark}" class="ln" stroke="#fff" data-w="stroke"/></g>`;
    },
    target: (h) => ({ o: h ? 1 : 0, s: h ? 0.9 : 1, n: h ? 9.6 : 3.4 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      at(E.eq, { transform: `translate(19.6 19.4) scale(${f(p.s)}) translate(-19.6 -19.4)` });
      at(E.lit, { opacity: f(o) }); at(E.eqW, { opacity: f(o) }); at(E.eqD, { opacity: f(1 - o) });
      at(E.read, { d: `M${f(20.9 - p.n)} 5.3H20.9` });
    }
  },
  {
    name: '货车',
    // A delivery truck: cargo box behind, cab in front. On hover it pulls forward, the body
    // bobbing on its springs until it settles, while the wheels roll along the ground.
    svg: (u) => {
      const box = rr(4.6, 4.2, 14.4, 13.4, KR);
      const cab = rp([[18, 8.4], [23.2, 8.4], [26.4, 12.6], [26.4, 17.6], [18, 17.6]], [1.8, 1.4, 1.6, KR, 0]);
      const win = rp([[20, 10.4], [22.2, 10.4], [24.4, 13.3], [20, 13.3]], [0.8, 0.6, 0.6, 0.8]);
      return `<g data-n="body">
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${box}" fill="${u.loS}"/></g></g><path d="${box}" ${OL}/>
        <path d="${lines(7.4, 8.2, [6])}" class="ln" stroke="#fff" data-w="stroke"/>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${cab}" fill="${u.upS}"/></g></g><path d="${cab}" ${OL}/>
        <path d="${win}" fill="#fff"/>
      </g>
      <g data-n="wheels">
        <circle cx="9.2" cy="19.4" r="2.6" ${DEEP}/><circle cx="9.2" cy="19.4" r="1.2" fill="#fff"/>
        <circle cx="22.2" cy="19.4" r="2.6" ${DEEP}/><circle cx="22.2" cy="19.4" r="1.2" fill="#fff"/>
      </g>`;
    },
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      const x = 1.2 * o, bob = -0.8 * (1 - o) * Math.sin(3 * Math.PI * o);
      at(E.body, { transform: `translate(${f(x)} ${f(bob)})` });
      at(E.wheels, { transform: `translate(${f(x)} 0)` });
    }
  },
  {
    name: '包裹',
    // A parcel whose two top flaps fold open on hover.
    svg: (u) => {
      const box = rr(5.2, 8.6, 20.6, 14.2, KR);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${box}" fill="${u.lo(14.2)}"/></g></g><path d="${box}" ${OL}/>
        <path d="${rr(14.2, 8.6, 2.6, 4.6, 0.6)}" fill="#fff"/>
        <g filter="${u.hi}"><path data-n="fl" fill="${u.upS}"/></g><path data-n="flO" ${OL}/>
        <g filter="${u.hi}"><path data-n="fr" fill="${u.upS}"/></g><path data-n="frO" ${OL}/>`;
    },
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      const l = rp([[5.2, 8.6], [15.4, 8.6], [15.4 - 2.6 * o, 6.2 - 2.8 * o], [5.2 - 2.8 * o, 6.2 - 1.6 * o]], [0.6, 0.6, 1, 1]);
      const r = rp([[15.6, 8.6], [25.8, 8.6], [25.8 + 2.8 * o, 6.2 - 1.6 * o], [15.6 + 2.6 * o, 6.2 - 2.8 * o]], [0.6, 0.6, 1, 1]);
      at(E.fl, { d: l }); at(E.flO, { d: l }); at(E.fr, { d: r }); at(E.frO, { d: r });
    }
  },
  {
    name: '快捷方式',
    // A grid of sites; on hover one tile lifts out, ready to open.
    svg: (u) => `
      <g filter="${u.sh}"><g filter="${u.hi}"><path d="${rr(5.2, 2.2, 20.6, 20.6, KR)}" fill="${u.loS}"/></g></g>
      <path d="${rr(5.2, 2.2, 20.6, 20.6, KR)}" ${OL}/>
      ${SHORTCUT_TILES.filter((t, i) => i !== 1).map(([x, y]) => `<path d="${rr(x, y, 7.3, 7.3, CR)}" fill="#fff"/>`).join('')}
      <g data-n="lift"><g filter="${u.sh}"><path d="${rr(0, 0, 7.3, 7.3, CR)}" fill="#fff"/></g><circle cx="3.65" cy="3.65" r="1.7" data-t="fill:#5393FF"/></g>`,
    target: (h) => ({ lift: h ? [16.9, 2.6, 1.14] : [16.5, 4.2, 1] }),
    draw(p, E) {
      const [x, y, s] = p.lift;
      at(E.lift, { transform: `translate(${f(x)} ${f(y)}) translate(3.65 3.65) scale(${f(s)}) translate(-3.65 -3.65)` });
    }
  },
  {
    name: '文档',
    // A page whose folded corner opens a little more on hover.
    svg: (u) => `<g filter="${u.sh}"><g filter="${u.hi}"><path data-n="pg" fill="${u.loS}"/></g></g><path data-n="pgO" ${OL}/>
      <path d="${lines(9.6, 13.4, [11.8, 8.2])}" class="ln" stroke="#fff" data-w="stroke"/>
      <g filter="${u.hi}"><path data-n="fold" fill="${u.upS}"/></g><path data-n="foldO" ${OL}/>`,
    target: (h) => ({ fold: h ? 8 : 6 }),
    draw(p, E) {
      const c = p.fold;
      const pg = rp([[6.3, 1.5], [24.7 - c, 1.5], [24.7, 1.5 + c], [24.7, 23.5], [6.3, 23.5]], [KR, 0.5, 0.5, KR, KR]);
      const fold = rp([[24.7 - c, 1.5], [24.7, 1.5 + c], [24.7 - c, 1.5 + c]], [0.4, 0.4, 1.2]);
      at(E.pg, { d: pg }); at(E.pgO, { d: pg }); at(E.fold, { d: fold }); at(E.foldO, { d: fold });
    }
  },
  {
    name: '扫码',
    // A QR code on a card with a scan bar lying across it. On hover the bar sweeps down
    // over the code and back up past the middle, then settles where it began.
    svg: (u) => {
      const card = rr(5.2, 2.2, 20.6, 20.6, KR), bar = rr(3.6, -1.2, 23.8, 2.4, 1.2);
      const finder = (x, y) => rr(x, y, 5.9, 5.9, 1.4) + rr(x + 1.6, y + 1.6, 2.7, 2.7, 0.6);
      const code = finder(7.4, 4.4) + finder(17.7, 4.4) + finder(7.4, 14.7) + rr(17.7, 14.7, 2.4, 2.4, 0.5) + rr(21.2, 18.2, 2.4, 2.4, 0.5);
      return `
      <g filter="${u.sh}"><g filter="${u.hi}"><path d="${card}" fill="${u.loS}"/></g></g>
      <path d="${card}" ${OL}/>
      <path d="${code}" fill-rule="evenodd" fill="#fff" data-w="fill"/>
      <g data-n="bar"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${bar}" fill="${u.upS}"/></g></g><path d="${bar}" ${OL}/></g>`;
    },
    // At rest and at the end the bar's outline meets both rows of the code exactly.
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      at(E.bar, { transform: `translate(0 ${f(12.5 + 7.6 * Math.sin(2 * Math.PI * o) * (1 - 0.35 * o))})` });
    }
  },
  {
    name: '照片',
    // Two prints, one behind the other: on hover the back one fans out to the left and
    // the front one tilts, like leafing through an album.
    svg: (u) => {
      const frame = rr(4, 5.6, 23, 16.1, KR), back = rr(6, 3.3, 19, 15, KR);
      return `
      <g data-n="back"><g filter="${u.sh}"><g filter="${u.hi}"><path d="${back}" fill="${u.lo(15)}"/></g></g><path d="${back}" ${OL}/></g>
      <g data-n="front">
        <clipPath id="${u.id('sky')}"><path d="${frame}"/></clipPath>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${frame}" fill="${u.upS}"/></g></g>
        <g clip-path="url(#${u.id('sky')})">
          <circle cx="20.4" cy="9.8" r="2.5" fill="#fff"/>
          <path d="${rp([[-1, 23], [-1, 20.2], [10.6, 10.8], [23, 20.8], [23, 23]], [0, 0, 1.8, 0, 0])}" fill="${u.loS}"/>
          <path d="${rp([[8, 23], [8, 21.4], [19.8, 13.2], [32, 20.8], [32, 23]], [0, 0, 1.8, 0, 0])}" fill="${u.pure('#5393FF')}"/>
        </g>
        <path d="${frame}" ${OL}/>
      </g>`;
    },
    target: (h) => ({ back: h ? [-1.4, -1.2, -9] : [0, 0, 0], front: h ? [0.6, 0.2, 4] : [0, 0, 0] }),
    draw(p, E) {
      at(E.back, { transform: `translate(${f(p.back[0])} ${f(p.back[1])}) rotate(${f(p.back[2])} 15.5 21.7)` });
      at(E.front, { transform: `translate(${f(p.front[0])} ${f(p.front[1])}) rotate(${f(p.front[2])} 15.5 21.7)` });
    }
  },
  {
    name: '色卡',
    // A swatch fan pinned at the bottom. At rest the three cards sit almost closed; on hover
    // they fan open around the pin, like flicking through a colour guide.
    svg: (u) => {
      const card = rr(11.3, 2.4, 8.4, 20, KR);
      const label = rp(R(11.3, 16.2, 8.4, 6.2), [0, 0, KR, KR]);
      const piece = (n, fill) => `
        <g filter="${u.sh}"><g filter="${u.hi}"><g data-n="${n}"><path d="${card}" fill="${fill}"/></g></g></g>
        <g data-n="${n}O"><path d="${label}" fill="#fff"/><path d="${card}" ${OL}/></g>`;
      return `${piece('l', u.loS)}${piece('r', u.pure('#5393FF'))}${piece('c', u.upS)}
        <circle cx="15.5" cy="19.6" r="1.3" ${DEEP}/>`;
    },
    target: (h) => ({ a: h ? 26 : 14 }),
    draw(p, E) {
      const rot = (a) => ({ transform: `rotate(${f(a)} 15.5 19.6)` });
      at(E.l, rot(-p.a)); at(E.lO, rot(-p.a));
      at(E.r, rot(p.a)); at(E.rO, rot(p.a));
      at(E.c, rot(0)); at(E.cO, rot(0));
    }
  },
  {
    name: '灯泡',
    // A bulb that lights up on hover.
    svg: (u) => {
      const glass = 'M11 15.6C8.8 14 7.4 11.6 7.4 9A8.1 8.1 0 0 1 23.6 9C23.6 11.6 22.2 14 20 15.6V17.6H11Z';
      const base = rr(10.8, 16.8, 9.4, 6.4, 2);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${glass}" fill="${u.upS}"/></g></g><path d="${glass}" ${OL}/>
        <circle data-n="glow" cx="15.5" cy="9.4" r="5" fill="#fff"/>
        <path d="M12.8 12.6L14.2 9.8L15.5 11.8L16.8 9.8L18.2 12.6" fill="none" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" ${DEEPS}/>
        <g filter="${u.hi}"><path d="${base}" fill="${u.loS}"/></g><path d="${base}" ${OL}/>
        <path d="${lines(12.8, 20, [5.4])}" class="ln" stroke="#fff" data-w="stroke"/>`;
    },
    target: (h) => ({ glow: h ? 0.85 : 0 }),
    draw(p, E) { at(E.glow, { opacity: f(p.glow) }); }
  },
  {
    name: '书本',
    // A closed book whose cover swings open on hover.
    svg: (u) => {
      const back = rr(6.3, 1.5, 18.4, 22, KR), cover = rr(6.3, 1.5, 18.4, 19.4, KR);
      return `<g filter="${u.sh}"><path d="${back}" fill="${u.loS}"/></g><path d="${back}" ${OL}/>
        <path d="${rr(7.8, 3, 15.6, 19.4, CR)}" fill="#fff"/>
        <path d="${lines(11.4, 8.4, [9.2, 6.6])}" ${ACC}/>
        <g data-n="cv"><g filter="${u.hi}"><path d="${cover}" fill="${u.loS}"/></g><path data-n="sh" d="${cover}" ${DEEP} opacity="0"/><path d="${cover}" ${OL}/>
          <path d="${lines(10.4, 7.6, [10.2])}" class="ln" stroke="#fff" data-w="stroke"/></g>`;
    },
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const o = Math.max(0, Math.min(1, p.o));
      at(E.cv, { transform: `translate(6.3 0) scale(${f(Math.max(0.001, 1 - 0.72 * o))} 1) translate(-6.3 0)` });
      at(E.sh, { opacity: f(0.35 * o) });
    }
  },
  {
    name: '相机',
    // A camera body with a lens in front; the aperture closes on hover like a shutter.
    svg: (u) => {
      const body = rr(4, 6.6, 23, 15.1, KR), top = rp(R(9.6, 3.6, 7.4, 4), [1.6, 1.6, 0, 0]);
      return `<g filter="${u.sh}"><path d="${top}" fill="${u.loS}"/></g><path d="${top}" ${OL}/>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${body}" fill="${u.loS}"/></g></g><path d="${body}" ${OL}/>
        <g filter="${u.hi}"><path d="${circ(15.5, 14.2, 5.4)}" fill="${u.upS}"/></g><path d="${circ(15.5, 14.2, 5.4)}" ${OL}/>
        <circle data-n="iris" cx="15.5" cy="14.2" ${DEEP}/>`;
    },
    target: (h) => ({ iris: h ? 1.2 : 2.8 }),
    draw(p, E) { at(E.iris, { r: f(p.iris) }); }
  },
  {
    name: '图表',
    // A bar chart whose bars rise and fall to new values on hover.
    svg: (u) => `<g filter="${u.sh}"><g filter="${u.hi}"><path d="${rr(5.2, 2.2, 20.6, 20.6, KR)}" fill="${u.loS}"/></g></g>
      <path d="${rr(5.2, 2.2, 20.6, 20.6, KR)}" ${OL}/>
      <path data-n="b1" fill="#fff"/><path data-n="b2" fill="#fff"/><path data-n="b3" fill="#fff"/>`,
    target: (h) => ({ hgt: h ? [10, 5.4, 13.4] : [5.4, 10.6, 7.6] }),
    draw(p, E) {
      [8.4, 13.7, 19].forEach((x, i) => {
        const hh = p.hgt[i];
        at(E['b' + (i + 1)], { d: rp(R(x, 20 - hh, 3.6, hh), [1, 1, 0.4, 0.4]) });
      });
    }
  },
  {
    name: '设置',
    svg: (u) => `
      <g filter="${u.sh}"><g filter="${u.hi}"><g data-n="gear"><path d="${GEAR}" fill="${u.loS}"/></g></g></g><g data-n="gearO"><path d="${GEAR}" ${OL}/></g>
      <path d="${circ(15.5, 12.5, 5.8)}" fill="#fff"/>
      <g filter="${u.hi}"><path data-n="hub" fill="${u.upS}"/></g>
      <path data-n="hubO" ${OL}/>`,
    target: (h) => ({ rot: h ? 60 : 0, hub: h ? 2.9 : 3.5 }),
    draw(p, E) {
      at(E.gear, { transform: `rotate(${f(p.rot)} 15.5 12.5)` }); at(E.gearO, { transform: `rotate(${f(p.rot)} 15.5 12.5)` });
      const d = circ(15.5, 12.5, p.hub);
      at(E.hub, { d }); at(E.hubO, { d });
    }
  },
  {
    name: '盾牌',
    // A shield with a lit half; it steps forward on hover.
    svg: (u) => {
      const sh = 'M15.5 1.4L24.2 4.8V11.4C24.2 17.2 20.6 21.6 15.5 23.8C10.4 21.6 6.8 17.2 6.8 11.4V4.8Z';
      return `<g data-n="g">
        <clipPath id="${u.id('half')}"><rect x="15.5" y="-2" width="16" height="30"/></clipPath>
        <g filter="${u.sh}"><g filter="${u.hi}"><path d="${sh}" fill="${u.loS}"/></g></g>
        <g clip-path="url(#${u.id('half')})"><g filter="${u.hi}"><path d="${sh}" fill="${u.upS}"/></g></g>
        <path d="${sh}" ${OL}/>
        <path d="M11.4 12.2L14.4 15.2L19.8 9.6" fill="none" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" ${DEEPS}/>
      </g>`;
    },
    target: (h) => ({ y: h ? -1 : 0, s: h ? 1.06 : 1 }),
    draw(p, E) { at(E.g, { transform: `translate(15.5 ${f(12.6 + p.y)}) scale(${f(p.s)}) translate(-15.5 -12.6)` }); }
  },
  {
    name: '便签',
    // A sticky note whose folded corner peels further on hover.
    svg: (u) => `<g filter="${u.sh}"><g filter="${u.hi}"><path data-n="note" fill="${u.loS}"/></g></g><path data-n="noteO" ${OL}/>
      <path d="${lines(8.6, 7.4, [13.8, 9.4])}" class="ln" stroke="#fff" data-w="stroke"/>
      <g filter="${u.hi}"><path data-n="fold" fill="${u.upS}"/></g><path data-n="foldO" ${OL}/>`,
    target: (h) => ({ cut: h ? 9 : 6.4 }),
    draw(p, E) {
      const c = p.cut;
      const note = rp([[5.2, 2.2], [25.8, 2.2], [25.8, 22.8 - c], [25.8 - c, 22.8], [5.2, 22.8]], [KR, KR, 0.6, 0.6, KR]);
      const fold = rp([[25.8, 22.8 - c], [25.8 - c, 22.8], [25.8 - c, 22.8 - c]], [0.5, 0.5, 1.2]);
      at(E.note, { d: note }); at(E.noteO, { d: note }); at(E.fold, { d: fold }); at(E.foldO, { d: fold });
    }
  },
  {
    name: '钥匙',
    // A key that turns over on hover, its teeth flipping to the other side.
    svg: (u) => {
      const shaft = rp([[13.6, 10.9], [28.2, 10.9], [28.2, 17.6], [25.4, 17.6], [25.4, 14.1], [23.6, 14.1], [23.6, 18.6], [20.8, 18.6], [20.8, 14.1], [13.6, 14.1]], [0.4, 0.9, 0.7, 0.7, 0.3, 0.3, 0.7, 0.7, 0.3, 0.4]);
      const head = circ(9.4, 12.5, 7) + circ(9.4, 12.5, 2.6);
      return `<g filter="${u.sh}"><g filter="${u.hi}"><g data-n="k"><path d="${shaft}" fill="${u.loS}"/><path d="${head}" fill-rule="evenodd" fill="${u.upS}"/></g></g></g>
        <g data-n="ko"><path d="${shaft}" ${OL}/><path d="${head}" fill-rule="evenodd" ${OL}/></g>`;
    },
    target: (h) => ({ o: h ? 1 : 0 }),
    draw(p, E) {
      const sy = Math.cos(Math.max(0, Math.min(1, p.o)) * Math.PI);
      const t = `translate(0 12.5) scale(1 ${f(Math.abs(sy) < 0.001 ? 0.001 : sy)}) translate(0 -12.5)`;
      at(E.k, { transform: t }); at(E.ko, { transform: t });
    }
  },
  {
    name: '退出',
    // A door with an arrow beside it. On hover the door swings open on its left hinge to
    // the bright outside and the arrow heads on out.
    svg: (u) => {
      const frame = rr(4, 1, 12.2, 23, KR), way = rp(R(7, 4, 6.2, 20), [1.6, 1.6, 0, 0]);
      return `
      <g filter="${u.sh}"><g filter="${u.hi}"><path d="${frame}" fill="${u.loS}"/></g></g>
      <path d="${frame}" ${OL}/>
      <path d="${way}" fill="#fff"/>
      <g filter="${u.hi}"><path data-n="leaf" fill="${u.upS}"/></g>
      <path data-n="leafO" ${OL}/>
      <circle data-n="knob" cy="14" r="1.2" ${DEEP}/>
      <g data-n="arrow"><path d="M20.3 12.5H24" fill="none" stroke-width="2.2" stroke-linecap="round" ${DEEPS}/>
        <path d="${rp([[23.6, 9.9], [27, 12.5], [23.6, 15.1]], 0.5)}" ${DEEP}/></g>`;
    },
    target: (h) => ({ s: h ? 0.5 : 1, x: h ? 1.4 : 0 }),
    draw(p, E) {
      const w = 6.2 * p.s, d = rp(R(7, 4, w, 20), [1.6, 1.6, 0, 0]);
      at(E.leaf, { d }); at(E.leafO, { d });
      // The knob keeps to the free edge and never leaves the narrowing leaf.
      at(E.knob, { cx: f(7 + w * (0.29 + 0.42 * p.s)) });
      at(E.arrow, { transform: `translate(${f(p.x)} 0)` });
    }
  }
];

export const ICONS_BY_NAME = Object.fromEntries(ICONS.map((icon) => [icon.name, icon]));
