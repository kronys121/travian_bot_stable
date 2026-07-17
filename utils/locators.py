"""
Центральный реестр CSS-селекторов интерфейса Travian.

Когда Travian обновляет вёрстку — правим ТОЛЬКО этот файл.
Селекторы сгруппированы по экранам/функциям игры.
"""

# ---------------------------------------------------------------------------
# Стройка (dorf1/dorf2, контракт здания)
# ---------------------------------------------------------------------------
BUILD = {
    'queue': '.buildingList ul li',
    'queue_timer': '.buildDuration span.timer[value]',
    'fields': '[data-aid][data-gid]',
    'level_label': '.labelLayer',
    'upgrade_btn': '.section1 button.green',
    'upgrade_btn_ad': '.section2 button.green',   # стройка с рекламой (-25% времени)
    # фиолетовая кнопка запуска видео-рекламы внутри section2
    'ad_video_btn': '.section2 button.videoFeatureButton',
    # кнопка воспроизведения видео в плеере рекламы (ID плеера динамический)
    'ad_play_btn': '[id^="player"] > div > div > div, .atg-gima-big-play-button',
    'ad_play_btn_small': '.atg-gima-play-button',
    'ad_mute_btn': '.atg-gima-audio-button.atg-gima-controlbar-btn',
    'ad_close_btn': '.atg-gima-close-button',
    'duration': '.buildDuration .timer',
    'tabs': '.contentNavi .tabItem, .contentNavi .navigate',
    'build_new_btn': 'button.green.new, button.green.build',
    # карточка контракта нового здания: #contract_building<gid>
    'contract_card': '#contract_building{gid}',
    # невыполненное требование постройки (класс error)
    'unmet_condition': '.upgradeButtonsContainer .buildingCondition.error',
    'free_crop': '.freeCrop_small .value, .freeCrop .value',
    'stockbar_free_crop': '.granary.stockBarButton #stockBarFreeCrop, #stockBarFreeCrop',
    # окно согласия при первом просмотре рекламы
    'ad_consent_checkbox': '.buttonWrapper.formV2 .checkbox',
    'ad_consent_ok': '.buttonWrapper.formV2 .textButtonV2.buttonFramed.dialogButtonOk.rectangle.withText.green',
}

# ---------------------------------------------------------------------------
# Диалоги (общие)
# ---------------------------------------------------------------------------
DIALOG = {
    'confirm': '#dialogContent button.green, .dialogVisible button.green',
    'close': '#dialogCancelButton',
    'confirm_transfer': '.actionButton .textButtonV2.withLoadingIndicator',
}

# ---------------------------------------------------------------------------
# Инвентарь героя (перенос ресурсов)
# ---------------------------------------------------------------------------
HERO_INVENTORY = {
    'res_max_btn': '.actionButton > button:nth-child(1)',
    'resource_row': '.resourceRowBody',
    'resource_count': '.count',
    'resource_input': '.resourceInput.formV2 input, .resourceInput input',
    'fillup_btn': 'button.textButtonV2.buttonFramed.fillup',
    # ящики ресурсов: класс предмета по имени ресурса
    'item_lumber': '.heroItems .item.item145',
    'item_clay': '.heroItems .item.item146',
    'item_iron': '.heroItems .item.item147',
    'item_crop': '.heroItems .item.item148',
}

# Соответствие ресурс -> класс предмета в инвентаре
RES_ITEM_CLASS = {
    'lumber': 'item145',
    'clay': 'item146',
    'iron': 'item147',
    'crop': 'item148',
}

# ---------------------------------------------------------------------------
# Кузница (smithy)
# ---------------------------------------------------------------------------
SMITHY = {
    'unit_rows': '.researchWrapper, .research',
    'cta_block': '.cta',
    # обычное улучшение: зелёная кнопка (type=button)
    'upgrade_btn_normal': 'button.textButtonV1.green',
    # улучшение за рекламу: фиолетовая кнопка (type=submit!)
    'upgrade_btn_ad': 'button.textButtonV1.purple',
}

# ---------------------------------------------------------------------------
# Общие элементы страницы
# ---------------------------------------------------------------------------
COMMON = {
    'stockbar_lumber': '#l1',
    'stockbar_clay': '#l2',
    'stockbar_iron': '#l3',
    'stockbar_crop': '#l4',
    'error_message': '#contract .errorMessage, .upgradeBlocked, .errorMessage',
}
