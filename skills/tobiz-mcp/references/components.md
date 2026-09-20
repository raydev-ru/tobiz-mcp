# Компоненты блоков: формы, кнопки, меню, карты, контакты

Всё ниже — из вендорских `editor.min.js` / `blocks2.js` и проверено на живом сайте.
Русские подписи полей смотри в `tobiz_describe_block` для конкретного типа блока.

## 1. Кнопки

Рендерер `btnRender(item, …)` собирает кнопку так:

* `use_form = 0` → это **ссылка**: `<a href="<link>">` (иначе `<div>`, по клику открывается форма);
  `use_form = 2` → добавляет класс `add_basket` (в корзину), `use_form = 3` → `open_card` (карточка товара);
* `surround` — заливка; без заливки и без своих границ рендерер сам ставит `border: 2px solid`;
* `style` — **пресет скругления** (id из таблицы редактора → `border-radius: <css>`, обычно 2px/4px/8px);
  `radius` — скругление **в `em`** и перекрывает пресет;
* `border_use` + `border_width` + `border_style` + `border_color` — своя рамка;
  `border_disable` — отключить рамку совсем;
* `shadow` — пресет тени (`box-shadow`), для `shadow = 3` цвет считается от цвета кнопки;
* типографика: `btn_fontf` (font-family), `font_size`, `fw` (font-weight), `line_height`,
  `letter_spacing`, `text_transform`, `white_space`;
* размер: `btn_width`, `btn_height` (min-height), `btn_padding`;
* цвета: `color` (фон при `surround`), `text_color`, `hover_color`, `text_color_hover`,
  `hover_border_color` / `hover_border_width` / `hover_border_style`;
* `animation` (при `surround`), `target` (в новой вкладке), `btn_icon*` (иконка на кнопке);
* аналитика: `metrica_event`, `fb_pixel`, `vk_pixel`, `gtag_event`;
* оплата: `action`, `url`, `amount`, `product_name`.

**Практика (проверено):**

* «кнопка 7px» = `radius = 7 / font_size` (0.35 при 20px, 0.389 при 18px, 0.412 при 17px).
  Рендерер выводит `border-radius: <radius>em` инлайн-стилем, поэтому он перекрывает вендорское
  `.btn1.surround{border-radius:2px}` — CSS-блок не нужен;
* **текст кнопок внутри форм** задаётся не полем, а автоконтрастом вендора:
  `--autocontrast-text-color` считается от фона (тёмный фон → белый текст). Поэтому тёмно-зелёная
  кнопка получает белый текст сама, а жёлтая/оранжевая — чёрный. Поле `text_color` на
  submit-кнопку не влияет.

## 2. Формы

Каркас (тип 306 и подобные):

```
<div class="form_wrapper [long_email] [del_border] [form_bg]" style="border-color:<brd_color>">
  <div class="form_bg_color" style="opacity:<form_bg_opacity>;background-color:<form_bg_color>"></div>
  <div class="form_title"><form_title></div>        ← при show_form_title
  <form action="handler.php" enctype="multipart/form-data"> …поля… </form>
  <div class="form_text"><form_text></div>           ← согласие/политика (HTML)
  <div class="popup_thanks">…</div>                  ← popupThanksRender(popup_thanks_title, popup_thanks_text)
</div>
```

Поля формы — массив `form1`, каждый элемент рисует `fieldRender`. **17 типов**:

| `type` | Что это | Ключи, которые надо помнить |
| --- | --- | --- |
| `text` | текст | `title`, `placeholder`, `description`, `required`, `title_hide` |
| `email` | e-mail | то же (в шапке формы есть флаг `long_email`) |
| `phone` | телефон | `set_mask` + `mask` → `data-mask` |
| `textarea` | многострочное | `white_space`, `line_height` |
| `select` | выпадающий список | `options` (строки) — **значение строкой**, не массивом |
| `radio` | радио | `options` |
| `checkbox` | галочка | `required` |
| `range` | ползунок | значения диапазона |
| `date` | дата | — |
| `number` | число | — |
| `file` | файл | форма уходит `multipart/form-data` |
| `hidden` | скрытое | не показывается, но уходит на сервер |
| `inline` | строка «текст + поле» | компактный вид |
| `list` | список | — |
| `captcha` | капча | рендерится как `input[name=norobot]` + `/captcha.php` |
| `btn` | кнопка отправки | см. ниже |

Общие ключи поля: `required`, `title_hide`, `placeholder`, `description`, `ftext_color`
(→ `--tf-input-color`), `border_color` (→ `--tf-input-focus-border-color`).

**Кнопка отправки** (`type: btn`) — это тот же `btnRender`, плюс data-атрибуты:
`action`, `metrica_event`, `fb_pixel`, `vk_pixel`, `gtag_event`, `url`, `amount`, `product_name`.
`surround` = заливка, `color` = цвет заливки, `style`/`radius` = скругление.

**Модальные формы:** `popupFormRender(title, text, fields[], className)` — обычная попап-форма
(её открывают кнопки с `use_form != 0`); `popupHTMLFormRender(html, …)` — своя HTML-форма
(включается флагом `replace_form_html`, пустое поле даёт заглушку «Замените HTML код»);
`popupThanksRender(title, text)` — окно «Спасибо» после отправки (поля `popup_thanks_title`,
`popup_thanks_text`); в вёрстке помечены `<!--noindex-->`.

**Грабли:** форма отправляется на `handler.php` средствами платформы — если ты заменяешь форму
своим HTML (`replace_form_html`), обработку заявок нужно обеспечивать самому.

## 3. Меню

* Данные — массив `menu1`. Элемент: `title`, `link`, **`level`** (0 — верхний уровень, 1 — подпункт,
  2 — под-подпункт), `target` (новая вкладка). Уровни задаются не вложенностью, а полем `level` —
  поэтому подпункты идут подряд после родителя.
* `menuRenderNG(menu1)` (актуальный) собирает вложенные `<ul>` по `level` и вешает
  `has-submenu` / `levelN`; `menuRender` — старая плоская версия; `renderMenus(count, …)` — несколько
  меню на блок (`menu1`, `menu2`, …).
* Настройки обёртки в блоках шапки: `menu_fs`, `menu_color`, `menu_fweight`, `menu_bg`,
  плюс CSS-переменные выпадающих списков: `--dropdown-menu-text-color`, `--dropdown-menu-hover-text-color`,
  `--dropdown-menu-shadow`, `--dropdown-menu-item-padding`.
* Мобильное меню: `.menu_mobile_btn` с классами `burger_forma`, `new_burger` и цветами
  `burger_color` / `burger_bg_color`; иконка — вендорская `/img/menu_burger.svg#menu`.
* Боковое меню — отдельная категория блоков (см. `block-catalog.md`).

**Грабли:** для анкоров внутри страницы ставь ссылку вида `#a_<block_id>` — вендор сам расставляет
id у блоков; при перестановке блоков анкоры остаются рабочими.

## 4. Логотип, телефоны, соцсети, рейтинг

* Логотип: `renderLogo(logo_url_enable, logo_use_text, logo_text, logo_url, logo_img, alt)` —
  либо `<img src="/img/200x0/<logo_img>">`, либо текстовое лого (`logo_text` как ссылка).
  `logoRender(item)` — вариант для блоков, где лого настраивается объектом
  (`use_image`, `image`, `image_size`, `text_size`, `color`).
* Телефоны: `getPhones(hide_phone, hide_phone2, phone1, phone2, phone_link, show_phone_icon,
  phone_color, phone_size, phone_weight)` — рендерит один-два телефона, при `phone_link` оборачивает
  в `tel:` (номер чистится `cleanPhoneNumber`), при `show_phone_icon` добавляет иконку.
  Цвет/размер/вес передаются CSS-переменными `--phone-text-color`, `--phone-font-size`,
  `--phone-font-weight`.
* Соцсети: `renderSocialIcons({show_icons, icons_figure, icons_color, icons_bg_color, show_vk, link_vk, …})` —
  пары `show_*`/`link_*` для VK, MAX, Telegram, WhatsApp, YouTube, Vimeo, Rutube, Дзен, Одноклассников,
  mail, Viber. Классы `sn-vk`, `sn-max` и т.д.
* Рейтинг: `rating_widget_show` + `rating_widget_html` — вставляется как готовый HTML.

## 5. Карты

`renderMap(className, map, map_center, scroll_off)` даёт только каркас:

```html
<div class="map" data-scroll_off="0" data-map-obj="<json>" data-map-center="<json>">
  <div class="map_inner"></div>
</div>
```

Сам объект карты и центр — это настройки блока (`map`, `map_center`), которые заполняет
Yandex-конструктор в редакторе; в HTML они попадают как JSON в `data-`атрибуты, а картинку рисует
скрипт сайта. Варианты блоков: карта с текстовой плашкой (`map_text_bg`), карта с фильтром
(`filter_on`), `scroll_off` — отключение прокрутки карты колесом.

**Грабли:** карта выглядит пустой не из-за ошибки в данных — пока скрипт не поднял её, внутри
только `.map_inner`. Скриншотом проверять бессмысленно, проверяй наличие `data-map-obj` и
настройки блока.

## 6. Видео, таймеры, quiz, калькулятор

* **Видео-фон**: только `https://kinescope.io/<id>` при `bg_mode=video` → `<iframe class="video_bg">`.
  Другие площадки в фон не встанут.
* **Видео в контенте**: `getVideoFrame(link)` понимает VK/VKVideo (`video_ext.php?oid=…&id=…`),
  Rutube, YouTube, Vimeo; плеер получает `data-video-id`.
* **Таймеры**: `renderTimer(class, {type, dd, dm, dy, monthly, weekly, hr, min}, color)` — классический
  отсчёт; `renderTimer2` — «кружки» (SVG-кольца). Тип отсчёта задаётся полем `type`.
* **QUIZ**: `renderQuiz({show_status, show_steps, show_discount, max_discount, min_discount, discount_alg})`
  + `quizFieldRender(вопрос)` — вопрос это поле с `title`, `type`, `required`, `use_image`,
  `sub_question` / `sub_question_hook` / `sub_question_num` (ветвление). Логику считает JS сайта.
* **Калькулятор**: `renderCalc({params, result, default_result})` — `params` рисует `calcFieldRender`,
  каждый `result` содержит `title` и `formula`; в HTML уезжает скрытый input с `data-formula` и
  `data-params`, а результат считает браузер. Формулы — строки-выражения от имён полей.

## 7. Приёмы, проверенные на живой сборке посадочной

* **Копия страницы ломает анкоры.** У копии блоки получают новые `block_id`, а `menu1` шапки и
  `menu1_ul` подвала продолжают указывать на id исходной страницы. После `tobiz_copy_page`
  перевяжи все ссылки на блоки заново, иначе меню ведёт в пустоту.
* **Выравнивание кнопок в карточках.** У блока тарифов нет опции «выровнять по кнопке», поэтому
  кнопки встают на разной высоте, если списки разной длины или пункт переносится на вторую строку.
  Уравняй количество пунктов, держи пункт в одну строку, затем проверь геометрию: у всех кнопок
  `getBoundingClientRect().top` должен совпадать (в проверенном примере 2879 / 2879 / 2879).
* **Крупный текст-заявление.** У текстового блока (например 132) заголовок рендерится около 32px —
  для акцентного заявления мало. Размер и ширину задавай инлайном в HTML заголовка
  (`<div style="max-width:680px;margin:0 auto"><span style="font-size:46px;line-height:1.15">…`):
  так же делает сам вендор в FAQ (`<span style="font-size:24px">`). Это правка содержимого, а не
  подмена стилей CSS-блоком.
* **Копия наследует SEO, slug и og-картинку** — перепропиши их через `tobiz_update_page`.
* **Скрытая страница всё равно отдаётся по адресу** `/slug/`: `tobiz_verify_page` и проверка
  вёрстки работают и для копии с `visible: false`.

## 8. Что делать, когда «ничего не помогло»

1. Проверь, что менял **те поля, которые есть в `tobiz_describe_block`** для этого типа.
2. Проверь, что не забыл `tobiz_save_page` — до него на сайте ничего не меняется.
3. Посмотри `tobiz_verify_page` (есть ли блок в публичном HTML) и только потом замеры в браузере.
4. Если элемент всё равно не поддаётся — это либо архивный/flex-блок с урезанным набором полей,
   либо поле, которого у типа нет по дизайну. Тогда выбирай другой тип блока (в каталоге 162 типа)
   вместо борьбы с CSS.
