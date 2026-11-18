import alchemakes from "../assets/filament-brands/theme/alchemakes.png";
import aliz from "../assets/filament-brands/theme/aliz.png";
import antinsky from "../assets/filament-brands/theme/antinsky.png";
import anycubic from "../assets/filament-brands/theme/anycubic.png";
import bambu from "../assets/filament-brands/bambu-lab.svg";
import bing3d from "../assets/filament-brands/theme/bing3d.png";
import biqu from "../assets/filament-brands/theme/biqu.png";
import cailab from "../assets/filament-brands/theme/cailab.png";
import chingLeung from "../assets/filament-brands/theme/ching-leung.png";
import creality from "../assets/filament-brands/creality.svg";
import elegoo from "../assets/filament-brands/theme/elegoo.png";
import esun from "../assets/filament-brands/theme/esun.png";
import inslogic from "../assets/filament-brands/theme/inslogic.png";
import jayo from "../assets/filament-brands/theme/jayo.png";
import karvax from "../assets/filament-brands/theme/karvax.png";
import kexcelled from "../assets/filament-brands/theme/kexcelled.png";
import kynix from "../assets/filament-brands/theme/kynix.png";
import rebirth from "../assets/filament-brands/theme/rebirth3d.png";
import sailner from "../assets/filament-brands/theme/sailner.png";
import snapmaker from "../assets/filament-brands/theme/snapmaker.png";
import sunlu from "../assets/filament-brands/theme/sunlu.png";
import xyd from "../assets/filament-brands/theme/xyd.png";
import alchemakesDark from "../assets/filament-brands/theme/alchemakes-dark.png";
import alizDark from "../assets/filament-brands/theme/aliz-dark.png";
import antinskyDark from "../assets/filament-brands/theme/antinsky-dark.png";
import anycubicDark from "../assets/filament-brands/theme/anycubic-dark.png";
import bing3dDark from "../assets/filament-brands/theme/bing3d-dark.png";
import biquDark from "../assets/filament-brands/theme/biqu-dark.png";
import cailabDark from "../assets/filament-brands/theme/cailab-dark.png";
import crealityDark from "../assets/filament-brands/theme/creality-dark.svg";
import elegooDark from "../assets/filament-brands/theme/elegoo-dark.png";
import esunDark from "../assets/filament-brands/theme/esun-dark.png";
import inslogicDark from "../assets/filament-brands/theme/inslogic-dark.png";
import jayoDark from "../assets/filament-brands/theme/jayo-dark.png";
import karvaxDark from "../assets/filament-brands/theme/karvax-dark.png";
import kynixDark from "../assets/filament-brands/theme/kynix-dark.png";
import rebirthDark from "../assets/filament-brands/theme/rebirth3d-dark.png";
import sailnerDark from "../assets/filament-brands/theme/sailner-dark.png";
import snapmakerDark from "../assets/filament-brands/theme/snapmaker-dark.png";
import xydDark from "../assets/filament-brands/theme/xyd-dark.png";

export interface FilamentBrand {
  intl: string;
  cn: string;
  logo?: string;
  logoDark?: string;
  aliases?: readonly string[];
}

export const filamentBrands: readonly FilamentBrand[] = [
  { intl: "Alchemakes", cn: "魔创", logo: alchemakes, logoDark: alchemakesDark },
  { intl: "Aliz", cn: "爱丽兹", logo: aliz, logoDark: alizDark, aliases: ["爱丽兹三维科技"] },
  { intl: "Antinsky", cn: "蚁在云端", logo: antinsky, logoDark: antinskyDark },
  { intl: "Anycubic", cn: "纵维立方", logo: anycubic, logoDark: anycubicDark },
  { intl: "Bambu Lab", cn: "拓竹", logo: bambu, aliases: ["Bambu", "bam", "ba", "拓"] },
  { intl: "Bing3D", cn: "必应", logo: bing3d, logoDark: bing3dDark },
  { intl: "BIQU", cn: "必趣", logo: biqu, logoDark: biquDark },
  { intl: "CAILAB", cn: "彩多屋", logo: cailab, logoDark: cailabDark },
  { intl: "CHING LEUNG", cn: "精亮", logo: chingLeung, aliases: ["精亮科技"] },
  { intl: "Creality", cn: "创想三维", logo: creality, logoDark: crealityDark },
  { intl: "ELEGOO", cn: "爱乐酷", logo: elegoo, logoDark: elegooDark },
  { intl: "eSUN", cn: "易生", logo: esun, logoDark: esunDark },
  { intl: "Inslogic", cn: "Inslogic", logo: inslogic, logoDark: inslogicDark },
  { intl: "JAYO", cn: "JAYO", logo: jayo, logoDark: jayoDark },
  { intl: "KARVAX", cn: "无境新材", logo: karvax, logoDark: karvaxDark },
  { intl: "Kexcelled", cn: "Kexcelled", logo: kexcelled },
  { intl: "KYNIX", cn: "KYNIX", logo: kynix, logoDark: kynixDark },
  { intl: "Polymaker", cn: "Polymaker" },
  { intl: "REBIRTH3D", cn: "瑞贝思", logo: rebirth, logoDark: rebirthDark },
  { intl: "Sailner", cn: "赛纳", logo: sailner, logoDark: sailnerDark, aliases: ["赛纳三维"] },
  { intl: "Snapmaker", cn: "快造", logo: snapmaker, logoDark: snapmakerDark, aliases: ["快造科技", "快造3D", "Snapmaker 3D"] },
  { intl: "SUNLU", cn: "三绿", logo: sunlu },
  { intl: "XYD", cn: "XYD小明", logo: xyd, logoDark: xydDark, aliases: ["XYD小明耗材", "小明电子科技", "XYD Xiaoming"] },
];

const darkLogos = new Map(filamentBrands.flatMap((brand) =>
  brand.logo && brand.logoDark ? [[brand.logo, brand.logoDark] as const] : [],
));

export const POLYMAKER_PANCHROMA_LOGO = "https://www.luminastudio.com.cn/logos/polymaker-teal.svg";
const polymakerLogoStart = Date.parse("2026-11-18T04:58:38Z");
const polymakerLogoEnd = Date.parse("2027-11-18T04:58:38Z");

export function polymakerPanchromaLogo(brand: string | undefined, series: string, materialType: string) {
  if (brand !== "Polymaker" || series.toLowerCase() !== "panchroma" || materialType.toLowerCase() !== "pla") return;
  const now = Date.now();
  return now >= polymakerLogoStart && now < polymakerLogoEnd ? POLYMAKER_PANCHROMA_LOGO : undefined;
}

export function filamentLogoSource(logo: string, theme: "light" | "dark"): string {
  return theme === "dark" ? darkLogos.get(logo) ?? logo : logo;
}
