# Движок блоков TOBIZ: как всё устроено

Разбор вендорских исходников: `editor.min.js` (движок и рендереры), `blocks2.js` (шаблоны 162 типов),
`flex_tools.min.js` (блок 1600), `script.min.js` (инициализация на сайте). Всё, что ниже, проверено
на живом сайте — если что-то расходится с этим файлом, верь замеру в браузере.

## 1. Главный принцип: сервер хранит готовый HTML

У блока нет «полей, которые сайт рендерит при показе». Есть:

* **`values`** — значения полей (то, что человек видит в редакторе);
* **`cache`** — готовый HTML, отрендеренный из `values` шаблоном блока;
* **`settings`** — служебное (позиция, видимость).

Публичная страница отдаёт `cache` как есть: `<div id="b_<block_id>">…</div>`. Отсюда следствия:

* поменял `values`, не перерендерив, — на сайте останется старый HTML (наш сервис перерендеривает
  все блоки страницы сам при `tobiz_save_page`, поэтому руками об этом думать не нужно);
* пустой `cache` = блок исчезает со страницы;
* «поправить HTML блока» нельзя — правка живёт до следующего сохранения.

## 2. Каркас секции (одинаковый у всех блочных типов)

```
<div class="section section<NNN> clip_<clip_path> [hide_in_desktop] [hide_in_mobile] [fixed] [animate] bg_mode_<bg_mode>"
     style="<background>; padding-top:<padd_top>px; padding-bottom:<padd_bottom>px; --clip_height:<clip_height>px;
            --light_opacity:…; --light_color:…; --light_bg:…; --light_radius:…; --light_padding:…; --txt_shadow:…">
  <video-bg> <div class="back_dark">(градиент) <div class="dark"> <div class="noise">(паттерн)
  <div class="section_inner [all_border] [width<inner_width>]">
     …заголовок, контент, кнопки…
  </div>
</div>
```

Общие поля, которые есть почти у каждого блока (ищи их в `tobiz_describe_block`):

| Поле | Что делает |
| --- | --- |
| `bg_mode` | `color` \| `image` \| `video` \| иначе — прозрачный фон |
| `bg` | цвет фона (при `bg_mode=color`) |
| `bg_image` | файл фона; подставляется как `/img/1920x0/<файл>`. `"null.png"` или пусто = фон не ставится |
| `bg_repeat` / `bg_position` / `bg_size` / `bg_size_custom` | повтор, позиция, размер (`cover`/`contain`/`custom` → `bg_size_custom`) |
| `padd_top` / `padd_bottom` | внутренние отступы секции, px |
| `back_dark` + `bg_opacity` + `opacity_color1/2` + `gradient_position` + `move_to` | цветная плашка-градиент поверх фона: `<div class="back_dark">` с `linear-gradient(to bottom, c1 X%, c2 100%)` |
| `dark` | затемнение фона (`<div class="dark">`) |
| `pattern` | текстура-шум `<div class="noise">` c `background-image:url(/img/<pattern>)` |
| `animate` / `fixed` | анимация появления, закрепление секции |
| `all_border` | рамка-контейнер внутри секции |
| `inner_width` | 940 / 1170 / 1400 / 1680 — ширина контейнера (класс `width…`) |
| `hide_in_mobile` / `hide_in_desktop` | показ только на большом/малом экране |
| `clip_path` / `clip_height` / `clip_influx` | косой срез секции |
| `title` / `sub_title` + `show_title` / `show_sub_title` / `title_margin` / `title_fweight` / `sub_title_*` | заголовок и подзаголовок секции |
| `light_layer` / `light_opacity` / `light_color` / `light_bg` / `light_radius` / `light_padding` / `light_backdrop` / `light_backdrop_blur` | «плашка под текстом» — единственный способ положить тёмный текст на светлый фон, когда вендорский CSS делает текст белым |
| `txt_shdw` + `txt_shdw_color` / `txt_shdw_blur` | тень текста |

**Практическое правило:** прежде чем лезть в CSS, пройди по этому списку — почти всё, что нужно
(фон, отступы, ширина, срез, закрепление, плашка под текстом), уже есть полем.

## 3. Изображения

| Где | Путь |
| --- | --- |
| фон секции | `/img/1920x0/<файл>` |
| логотип в шапке/подвале | `/img/200x0/<файл>` |
| обычные картинки в блоках | `/img/<W>x0/<файл>` — ширину подставляет `imageSize()`, а `tobiz_set_block_image` / `tobiz_upload_image` возвращают имя файла, который нужен полю |
| галереи/миниатюры | миниатюра = тот же файл с другим префиксом ширины |

Файл всегда указывается **именем** (`abc123.png`), а не URL. Ленивая загрузка: `lcpImage` /
`loading="lazy"` — если картинка не грузится, проверь имя, а не поле.

## 4. Массивы внутри `values` — заменяются целиком

Поля-коллекции (`arr1` в списках, `form1` в формах, `menu1` в меню, `params`/`result` в
калькуляторе, вопросы quiz и т.п.) — это массивы объектов. Правка одной записи:

1. `tobiz_get_block` → достать массив целиком;
2. изменить нужный элемент в памяти;
3. `tobiz_update_block` с **полным** массивом.

Передача одного элемента вместо массива затирает остальные. Если элемент нужно добавить — скопируй
существующий и поменяй значения: у каждого типа свой обязательный набор ключей, и «дописать с нуля»
обычно ломает рендер.

## 5. Полный список рендереров вендора

Что вызывает шаблон и что за это отвечает (полезно, когда нужно понять, какое поле за что держится):

| Хелпер | Отвечает за |
| --- | --- |
| `renderBgCSS(bg_mode, bg, bg_image, [repeat, position, size, size_custom])` | фон секции |
| `renderVideoBG(bg_mode, video_bg)` | видео-фон (только `https://kinescope.io/<id>` → `<iframe class="video_bg">`) |
| `renderGradiend`, `renderDark`, `renderPattern`, `renderPatternNew` | цветная плашка, затемнение, текстура |
| `imageSize(w, ratio)` / `lcpImage` | имена и префиксы картинок, приоритетная загрузка |
| `btnRender(btn, …, title, …)` | кнопка на странице (см. `components.md`) |
| `fieldRender(field)` | поле формы и submit-кнопка (17 типов полей) |
| `popupFormRender`, `popupHTMLFormRender`, `popupThanksRender` | модальные формы, своя HTML-форма, окно «Спасибо» |
| `menuRender` / `menuRenderNG` / `renderMenus` | меню (плоское / с уровнями / несколько меню) |
| `renderLogo`, `logoRender` | логотип в шапке/подвале, лого-текст |
| `getPhones(...)` | телефоны шапки/подвала, `tel:`-ссылки, иконка |
| `renderSocialIcons(settings)` | иконки соцсетей (VK, MAX, TG, WhatsApp, YouTube, Vimeo, Rutube, Дзен, Одноклассники, mail, Viber) |
| `renderMap(className, map, map_center, scroll_off)` | карта (Яндекс) — разметка пустая, данные в `data-map-obj` / `data-map-center` |
| `renderTimer` / `renderTimer2` | таймеры (обратный отсчёт, «кружки») |
| `renderCalc` + `calcFieldRender` | калькулятор (формулы считает JS на сайте) |
| `renderQuiz` + `quizFieldRender` | QUIZ-конструктор (шаги, прогресс, скидка) |
| `getVideoFrame` / `videoId` | вставка видео (VK, Rutube, YouTube, Vimeo) |
| `renderQuiz`, `renderCalc`, `renderSocialIcons` | см. выше |
| `stripTags`, `guid`, `helper`, `cloneDeep` | утилиты |
| `start/stop/error/success/complete/beforeSend`, `get/set` | ajax и доступ к вложенным полям данных |
| `beforeBlockRender` / `afterBlockRender` | крючки жизненного цикла рендера блока |

## 6. Как убедиться, что понял блок

1. `tobiz_describe_block` — имена полей, русские подписи, типы, дефолты (это истина в последней
   инстанции для конкретного типа);
2. `tobiz_get_block` — текущие значения и то, что реально лежит в массивах;
3. правка → `tobiz_save_page` → `tobiz_verify_page` (публичная вёрстка) → при сомнениях замер
   вычисленных стилей в браузере.

Если поле есть в этом файле, но его нет в `tobiz_describe_block` — значит у типа блока своя
урезанная схема: работает только то, что описано инструментом.
