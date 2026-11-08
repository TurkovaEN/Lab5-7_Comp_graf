# Подключение модулей
import ctypes  # вызовы функций Windows
import math  # логарифм и корень
import os  # имя файла без пути
import struct  # сборка заголовка DIB
import tkinter as tk  # окно и виджеты
from tkinter import filedialog, messagebox, ttk  # диалоги и оформление
from PIL import Image, ImageGrab, ImageTk  # ввод-вывод и показ картинки

# Настройки программы
HISTORY_LIMIT = 12  # сколько шагов можно отменить
MIN_SELECTION = 3  # минимальный размер выделения
WORK_LIMIT = 1600  # большая сторона рабочей копии
IMAGE_TYPES = [("Изображения", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"), ("Все файлы", "*.*")]  # форматы для диалога

# Функции Windows для буфера обмена
user32 = ctypes.windll.user32  # функции окна
kernel32 = ctypes.windll.kernel32  # функции памяти
kernel32.GlobalAlloc.restype = ctypes.c_void_p  # возвращаем адрес блока
kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]  # флаги и размер
kernel32.GlobalLock.restype = ctypes.c_void_p  # адрес памяти блока
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]  # хэндл блока
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]  # хэндл блока
user32.OpenClipboard.argtypes = [ctypes.c_void_p]  # окно-владелец
user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]  # формат и блок
user32.SetClipboardData.restype = ctypes.c_void_p  # хэндл данных


def clamp(value):
    # Приводим значение к диапазону яркости
    if value < 0:  # значение ниже нуля
        return 0  # берём минимум
    if value > 255:  # значение выше максимума
        return 255  # берём максимум
    return int(value)  # иначе просто округляем


def image_to_pixels(image):
    # Картинка превращается в список строк с пикселями
    if image.mode != "RGB":  # нужны три канала
        image = image.convert("RGB")  # приводим режим
    width, height = image.size  # размеры картинки
    data = image.tobytes()  # все байты пикселей подряд
    rows = []  # здесь будут строки пикселей
    for y in range(height):  # идём по строкам
        start = y * width * 3  # начало строки в байтах
        line = data[start:start + width * 3]  # байты одной строки
        rows.append([[line[i], line[i + 1], line[i + 2]] for i in range(0, len(line), 3)])  # собираем пиксели
    return width, height, rows  # размеры и пиксели


def read_image(image):
    # Рабочая копия картинки с ограничением размера
    image = image.convert("RGB")  # три канала
    small = max(image.size) > WORK_LIMIT  # картинка слишком большая
    if small:  # уменьшаем копию
        ratio = WORK_LIMIT / max(image.size)  # коэффициент уменьшения
        size = (max(1, int(image.width * ratio)), max(1, int(image.height * ratio)))  # новый размер
        image = image.resize(size, Image.LANCZOS)  # уменьшенная копия
    width, height, rows = image_to_pixels(image)  # пиксели копии
    return width, height, rows, small  # размеры, пиксели, признак уменьшения


def pixels_to_image(width, height, rows):
    # Пиксели превращаются обратно в картинку
    flat = [c for row in rows for pixel in row for c in pixel]  # вытягиваем каналы в один список
    return Image.frombytes("RGB", (width, height), bytes(flat))  # картинка из байтов


def copy_pixels(rows):
    # Копия пикселей для истории и возврата
    return [row[:] for row in rows]  # пиксели не меняются на месте, хватит копии строк


def crop_pixels(rows, region):
    # Вырезаем прямоугольную область
    x1, y1, x2, y2 = region  # границы области
    return [row[x1:x2] for row in rows[y1:y2]]  # нужные строки и столбцы


def brightness_of(r, g, b):
    # Яркость пикселя по весам каналов
    return (299 * r + 587 * g + 114 * b) // 1000  # целое число 0..255


def make_lut(func):
    # Таблица пересчёта всех уровней яркости
    return [clamp(func(value)) for value in range(256)]  # считаем каждое значение


def apply_lut(rows, lut):
    # Таблица применяется к каждому каналу
    return [[[lut[r], lut[g], lut[b]] for r, g, b in row] for row in rows]  # новые пиксели


def change_brightness(rows, delta):
    # Преобразование яркости сдвигом
    lut = make_lut(lambda value: value + delta)  # таблица сдвига
    return apply_lut(rows, lut)  # применяем таблицу


def change_contrast(rows, factor):
    # Преобразование контрастности
    lut = make_lut(lambda value: (value - 128) * factor + 128)  # растяжение вокруг середины
    return apply_lut(rows, lut)  # применяем таблицу


def make_negative(rows):
    # Негатив изображения
    lut = make_lut(lambda value: 255 - value)  # таблица инверсии
    return apply_lut(rows, lut)  # применяем таблицу


def to_gray(rows, method):
    # Переход к оттенкам серого
    result = []  # новые строки
    for row in rows:  # по строкам
        new_row = []  # новая строка
        for r, g, b in row:  # по пикселям
            if method == "Среднее":  # простое среднее каналов
                value = (r + g + b) // 3  # сумма делится на три
            elif method == "Максимум":  # самый светлый канал
                value = max(r, g, b)  # берём максимум
            else:  # взвешенная яркость
                value = brightness_of(r, g, b)  # стандартные веса
            new_row.append([value, value, value])  # серый пиксель
        result.append(new_row)  # добавляем строку
    return result  # готовые пиксели


def histogram(rows):
    # Гистограмма яркости
    hist = [0] * 256  # счётчики для всех уровней
    for row in rows:  # по строкам
        for r, g, b in row:  # по пикселям
            hist[brightness_of(r, g, b)] += 1  # плюс один пиксель уровню
    return hist  # готовый массив


def mean_threshold(hist):
    # Порог по средней яркости
    total = sum(hist)  # всего пикселей
    if total == 0:  # пустая область
        return 128  # средний уровень
    return int(sum(i * hist[i] for i in range(256)) / total)  # среднее значение


def median_threshold(hist):
    # Порог по медиане яркости
    total = sum(hist)  # всего пикселей
    if total == 0:  # пустая область
        return 128  # средний уровень
    acc = 0  # накопленное число пикселей
    for i in range(256):  # идём по уровням
        acc += hist[i]  # добавляем уровень
        if acc >= total / 2:  # дошли до половины
            return i  # это медиана
    return 128  # запасной ответ


def otsu_threshold(hist):
    # Порог по Оцу
    total = sum(hist)  # всего пикселей
    if total == 0:  # пустая область
        return 128  # средний уровень
    sum_all = sum(i * hist[i] for i in range(256))  # сумма всех яркостей
    weight_back = 0  # пикселей в тёмном классе
    sum_back = 0  # сумма яркостей тёмного класса
    best_variance = -1  # лучшая дисперсия
    best_threshold = 128  # лучший порог
    for t in range(256):  # перебираем пороги
        weight_back += hist[t]  # уровень уходит в тёмный класс
        if weight_back == 0:  # тёмный класс пуст
            continue  # пропускаем порог
        weight_front = total - weight_back  # пикселей в светлом классе
        if weight_front == 0:  # светлый класс пуст
            break  # дальше искать нет смысла
        sum_back += t * hist[t]  # сумма тёмного класса
        mean_back = sum_back / weight_back  # среднее тёмного
        mean_front = (sum_all - sum_back) / weight_front  # среднее светлого
        variance = weight_back * weight_front * (mean_back - mean_front) ** 2  # межклассовая дисперсия
        if variance > best_variance:  # нашли вариант лучше
            best_variance = variance  # запоминаем дисперсию
            best_threshold = t  # запоминаем порог
    return best_threshold  # готовый порог


def binarize(rows, threshold):
    # Бинаризация по порогу
    result = []  # новые строки
    for row in rows:  # по строкам
        new_row = []  # новая строка
        for r, g, b in row:  # по пикселям
            value = 255 if brightness_of(r, g, b) > threshold else 0  # сравнение с порогом
            new_row.append([value, value, value])  # чёрный или белый
        result.append(new_row)  # добавляем строку
    return result  # готовые пиксели


def equalize(rows):
    # Выравнивание гистограммы
    hist = histogram(rows)  # исходная гистограмма
    total = sum(hist)  # всего пикселей
    if total == 0:  # пустая область
        return copy_pixels(rows)  # менять нечего
    lut = [0] * 256  # таблица новых уровней
    acc = 0  # накопленная сумма пикселей
    for i in range(256):  # по уровням
        acc += hist[i]  # накапливаем пиксели
        lut[i] = clamp(round(acc * 255 / total))  # уровень по функции распределения
    return apply_lut(rows, lut)  # применяем таблицу


def stretch(rows):
    # Растяжение гистограммы на весь диапазон
    counts = [0] * 256  # счётчики значений каналов
    for row in rows:  # по строкам
        for r, g, b in row:  # по пикселям
            counts[r] += 1  # красный канал
            counts[g] += 1  # зелёный канал
            counts[b] += 1  # синий канал
    low = 0  # минимальное значение
    for i in range(256):  # ищем первое занятое значение
        if counts[i] > 0:  # значение встречается
            low = i  # это минимум
            break  # дальше не ищем
    high = 255  # максимальное значение
    for i in range(255, -1, -1):  # ищем последнее занятое значение
        if counts[i] > 0:  # значение встречается
            high = i  # это максимум
            break  # дальше не ищем
    if high <= low:  # диапазона нет
        return copy_pixels(rows)  # оставляем как есть
    scale = 255 / (high - low)  # коэффициент растяжения
    lut = [clamp((value - low) * scale) for value in range(256)]  # таблица растяжения
    return apply_lut(rows, lut)  # применяем таблицу


def statistics(rows):
    # Статистические характеристики яркости
    hist = histogram(rows)  # гистограмма яркости
    total = sum(hist)  # число пикселей
    if total == 0:  # пустая область
        return None  # считать нечего
    low = 0  # минимальная яркость
    for i in range(256):  # идём по уровням
        if hist[i] > 0:  # уровень встречается
            low = i  # это минимум
            break  # дальше не ищем
    high = 255  # максимальная яркость
    for i in range(255, -1, -1):  # идём с конца
        if hist[i] > 0:  # уровень встречается
            high = i  # это максимум
            break  # дальше не ищем
    mean = sum(i * hist[i] for i in range(256)) / total  # средняя яркость
    variance = sum((i - mean) ** 2 * hist[i] for i in range(256)) / total  # дисперсия
    acc = 0  # накопленное число пикселей
    median = 0  # медиана
    for i in range(256):  # по уровням
        acc += hist[i]  # накапливаем
        if acc >= total / 2:  # дошли до половины
            median = i  # это медиана
            break  # дальше не ищем
    mode = hist.index(max(hist))  # мода, самый частый уровень
    entropy = 0.0  # энтропия
    for count in hist:  # по уровням
        if count > 0:  # уровень встречается
            p = count / total  # вероятность уровня
            entropy -= p * math.log2(p)  # слагаемое энтропии
    return {"min": low, "max": high, "mean": mean, "variance": variance, "std": math.sqrt(variance),
            "median": median, "mode": mode, "entropy": entropy, "count": total}  # все характеристики


def copy_to_clipboard(width, height, rows):
    # Кладём изображение в буфер обмена как DIB
    pad = (4 - (width * 3) % 4) % 4  # выравнивание строк до четырёх байт
    data = bytearray()  # байты пикселей снизу вверх
    for y in range(height - 1, -1, -1):  # DIB хранится снизу вверх
        for r, g, b in rows[y]:  # по пикселям строки
            data += bytes((b, g, r))  # порядок каналов BGR
        data += b"\x00" * pad  # добиваем строку до выравнивания
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(data), 2835, 2835, 0, 0)  # заголовок DIB
    block = header + bytes(data)  # полный блок для буфера
    if not user32.OpenClipboard(None):  # буфер занят другой программой
        raise OSError("буфер обмена занят")  # сообщаем об ошибке
    try:  # буфер захвачен
        user32.EmptyClipboard()  # очищаем буфер
        handle = kernel32.GlobalAlloc(0x0042, len(block))  # память под блок
        pointer = kernel32.GlobalLock(handle)  # адрес блока
        ctypes.memmove(pointer, block, len(block))  # копируем блок в память
        kernel32.GlobalUnlock(handle)  # отпускаем блок
        user32.SetClipboardData(8, handle)  # 8 это формат CF_DIB
    finally:  # буфер надо закрыть всегда
        user32.CloseClipboard()  # отпускаем буфер


class ImageEditor(tk.Tk):
    # Главное окно программы
    def __init__(self):
        super().__init__()  # создаём окно
        self.title("Коррекция фотоизображения")  # заголовок окна
        self.geometry("1180x780")  # стартовый размер окна
        self.minsize(900, 620)  # меньше окно не делаем
        self.width = 0  # ширина картинки
        self.height = 0  # высота картинки
        self.rows = None  # пиксели текущей картинки
        self.original = None  # копия загруженной картинки
        self.history = []  # состояния для отмены
        self.selection = None  # выделенная область
        self.scale = 1.0  # масштаб показа
        self.shift = (0, 0)  # смещение картинки на холсте
        self.photo = None  # картинка для холста
        self.pil_image = None  # кэш картинки для показа
        self.drag_start = None  # начало протяжки мышью
        self.last_size = (0, 0)  # прошлый размер холста
        self.hist_info = None  # данные гистограммы для подсказки
        self.hist_level = None  # уровень под курсором
        self.build_interface()  # собираем интерфейс
        self.bind("<Configure>", self.on_resize)  # следим за размером окна

    def build_interface(self):
        # Прокручиваемая панель управления
        holder = ttk.Frame(self, padding=(10, 8, 0, 0))  # контейнер панели
        holder.grid(row=0, column=0, sticky="ns")  # ставим слева
        holder.rowconfigure(0, weight=1)  # панель тянется по высоте
        self.panel_canvas = tk.Canvas(holder, width=286, highlightthickness=0)  # холст прокрутки
        self.panel_canvas.grid(row=0, column=0, sticky="ns")  # место холста
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.panel_canvas.yview)  # полоса прокрутки
        scroll.grid(row=0, column=1, sticky="ns")  # справа от холста
        self.panel_scroll = scroll  # ссылка на полосу
        self.panel_canvas.configure(yscrollcommand=scroll.set)  # связываем полосу и холст
        panel = ttk.Frame(self.panel_canvas)  # рамка с блоками
        panel.columnconfigure(0, weight=1)  # блоки по ширине панели
        self.panel_frame = panel  # ссылка на рамку
        self.panel_window = self.panel_canvas.create_window((0, 0), window=panel, anchor="nw")  # рамка на холсте
        panel.bind("<Configure>", self.on_panel_configure)  # следим за высотой блоков
        self.panel_canvas.bind("<Configure>", self.on_panel_canvas)  # следим за шириной панели
        self.bind_all("<MouseWheel>", self.on_wheel)  # колесо мыши крутит панель

        # Блок загрузки и сохранения
        file_box = ttk.LabelFrame(panel, text="Файл", padding=5)  # рамка блока
        file_box.grid(row=0, column=0, sticky="ew", pady=2)  # место в панели
        file_box.columnconfigure(0, weight=1)  # первая колонка кнопок
        file_box.columnconfigure(1, weight=1)  # вторая колонка кнопок
        ttk.Button(file_box, text="Из файла", command=self.load_file).grid(row=0, column=0, sticky="ew", padx=1, pady=1)  # загрузка файла
        ttk.Button(file_box, text="Из буфера", command=self.load_clipboard).grid(row=0, column=1, sticky="ew", padx=1, pady=1)  # загрузка из буфера
        ttk.Button(file_box, text="В файл", command=self.save_file).grid(row=1, column=0, sticky="ew", padx=1, pady=1)  # сохранение копии
        ttk.Button(file_box, text="В буфер", command=self.copy_clipboard).grid(row=1, column=1, sticky="ew", padx=1, pady=1)  # копия в буфер
        ttk.Button(file_box, text="К исходному", command=self.reset_image).grid(row=2, column=0, sticky="ew", padx=1, pady=1)  # возврат к загруженному
        ttk.Button(file_box, text="Отменить", command=self.undo).grid(row=2, column=1, sticky="ew", padx=1, pady=1)  # шаг назад

        # Блок выделения области
        sel_box = ttk.LabelFrame(panel, text="Выделение", padding=5)  # рамка блока
        sel_box.grid(row=1, column=0, sticky="ew", pady=2)  # место в панели
        sel_box.columnconfigure(0, weight=1)  # одна колонка
        ttk.Button(sel_box, text="Снять выделение", command=self.clear_selection).grid(row=0, column=0, sticky="ew")  # сброс области
        ttk.Label(sel_box, text="Протяните мышью по картинке", foreground="#666").grid(row=1, column=0, sticky="w", pady=(2, 0))  # подсказка
        ttk.Label(sel_box, text="преобразования идут по выделению", foreground="#666").grid(row=2, column=0, sticky="w")  # уточнение

        # Блок яркости
        bright_box = ttk.LabelFrame(panel, text="Яркость (сдвиг)", padding=5)  # рамка блока
        bright_box.grid(row=2, column=0, sticky="ew", pady=2)  # место в панели
        bright_box.columnconfigure(0, weight=1)  # одна колонка
        self.bright_scale = tk.Scale(bright_box, from_=-100, to=100, orient="horizontal", resolution=1)  # ползунок сдвига
        self.bright_scale.grid(row=0, column=0, sticky="ew")  # место ползунка
        ttk.Button(bright_box, text="Применить", command=self.do_brightness).grid(row=1, column=0, sticky="ew", pady=(2, 0))  # запуск

        # Блок контрастности
        contrast_box = ttk.LabelFrame(panel, text="Контрастность (сдвиг, %)", padding=5)  # рамка блока
        contrast_box.grid(row=3, column=0, sticky="ew", pady=2)  # место в панели
        contrast_box.columnconfigure(0, weight=1)  # одна колонка
        self.contrast_scale = tk.Scale(contrast_box, from_=-100, to=100, orient="horizontal", resolution=1)  # ползунок контраста
        self.contrast_scale.grid(row=0, column=0, sticky="ew")  # место ползунка
        ttk.Button(contrast_box, text="Применить", command=self.do_contrast).grid(row=1, column=0, sticky="ew", pady=(2, 0))  # запуск

        # Блок цветности
        color_box = ttk.LabelFrame(panel, text="Цветность", padding=5)  # рамка блока
        color_box.grid(row=4, column=0, sticky="ew", pady=2)  # место в панели
        color_box.columnconfigure(0, weight=1)  # одна колонка
        self.gray_method = tk.StringVar(value="Взвешенная")  # способ перевода в серое
        ttk.Combobox(color_box, textvariable=self.gray_method, values=["Взвешенная", "Среднее", "Максимум"], state="readonly").grid(row=0, column=0, sticky="ew")  # выбор способа
        ttk.Button(color_box, text="В оттенки серого", command=self.do_gray).grid(row=1, column=0, sticky="ew", pady=(2, 5))  # запуск
        self.bin_method = tk.StringVar(value="Порог (вручную)")  # способ выбора порога
        ttk.Combobox(color_box, textvariable=self.bin_method, values=["Порог (вручную)", "Оцу", "Средняя яркость", "Медиана"], state="readonly").grid(row=2, column=0, sticky="ew")  # выбор порога
        ttk.Label(color_box, text="порог бинаризации", foreground="#666").grid(row=3, column=0, sticky="w", pady=(3, 0))  # подпись порога
        self.threshold_scale = tk.Scale(color_box, from_=0, to=255, orient="horizontal", resolution=1)  # ползунок порога
        self.threshold_scale.set(128)  # начальный порог
        self.threshold_scale.grid(row=4, column=0, sticky="ew")  # место ползунка
        ttk.Button(color_box, text="Бинаризовать", command=self.do_binarize).grid(row=5, column=0, sticky="ew", pady=(2, 5))  # запуск
        ttk.Button(color_box, text="Негатив", command=self.do_negative).grid(row=6, column=0, sticky="ew")  # запуск

        # Блок гистограммы
        hist_box = ttk.LabelFrame(panel, text="Гистограмма", padding=5)  # рамка блока
        hist_box.grid(row=5, column=0, sticky="ew", pady=2)  # место в панели
        hist_box.columnconfigure(0, weight=1)  # первая колонка
        hist_box.columnconfigure(1, weight=1)  # вторая колонка
        self.hist_shown = tk.BooleanVar(value=False)  # гистограмма скрыта
        ttk.Checkbutton(hist_box, text="Показать", variable=self.hist_shown, command=self.toggle_histogram).grid(row=0, column=0, columnspan=2, sticky="w")  # галочка показа
        ttk.Button(hist_box, text="Выровнять", command=self.do_equalize).grid(row=1, column=0, sticky="ew", padx=1, pady=2)  # выравнивание
        ttk.Button(hist_box, text="Растянуть", command=self.do_stretch).grid(row=1, column=1, sticky="ew", padx=1, pady=2)  # растяжение
        panel.update_idletasks()  # сразу считаем размеры блоков
        self.panel_canvas.configure(scrollregion=self.panel_canvas.bbox("all"))  # область прокрутки
        self.update_scrollbar()  # полоса только при нехватке места

        # Правая часть с картинкой
        view = ttk.Frame(self, padding=(0, 8, 8, 0))  # контейнер просмотра
        view.grid(row=0, column=1, sticky="nsew")  # ставим справа
        view.rowconfigure(0, weight=1)  # холст забирает высоту
        view.columnconfigure(0, weight=1)  # холст забирает ширину
        self.canvas = tk.Canvas(view, bg="#2b2b2b", highlightthickness=0)  # холст для картинки
        self.canvas.grid(row=0, column=0, sticky="nsew")  # место холста
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_press)  # начало выделения
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)  # протяжка рамки
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_release)  # конец выделения
        self.hist_frame = ttk.LabelFrame(view, text="Гистограмма яркости: уровень яркости / число пикселей", padding=4)  # рамка графика
        self.hist_frame.grid(row=1, column=0, sticky="ew", pady=(6, 0))  # место под холстом
        self.hist_canvas = tk.Canvas(self.hist_frame, height=150, bg="white", highlightthickness=1, highlightbackground="#ccc")  # холст графика
        self.hist_canvas.pack(fill="x")  # график по ширине
        self.hist_canvas.bind("<Motion>", self.on_hist_motion)  # подсказка по столбику
        self.hist_canvas.bind("<Leave>", self.on_hist_leave)  # курсор ушёл с графика
        self.hist_frame.grid_remove()  # по умолчанию скрыта

        # Нижняя строка со статистикой
        bottom = ttk.Frame(self, padding=(10, 4))  # контейнер строки
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew")  # место внизу
        bottom.columnconfigure(0, weight=1)  # текст по ширине
        self.stats_label = ttk.Label(bottom, text="Изображение не загружено", font=("Consolas", 9))  # характеристики
        self.stats_label.grid(row=0, column=0, sticky="w")  # слева
        self.status_label = ttk.Label(bottom, text="Готово", foreground="#666")  # сообщения
        self.status_label.grid(row=1, column=0, sticky="w")  # под характеристиками

        # Растягивание окна
        self.rowconfigure(0, weight=1)  # верхняя часть растягивается
        self.columnconfigure(1, weight=1)  # правая часть растягивается

    def set_status(self, text):
        # Сообщение в нижней строке
        self.status_label.config(text=text)  # меняем текст

    def set_pixels(self, width, height, rows):
        # Новые пиксели и сброс кэша показа
        self.width = width  # ширина картинки
        self.height = height  # высота картинки
        self.rows = rows  # рабочие пиксели
        self.pil_image = None  # кэш устарел

    def region(self):
        # Область обработки
        if self.selection is None:  # выделения нет
            return 0, 0, self.width, self.height  # обрабатываем всё
        return self.selection  # обрабатываем выделение

    def region_rows(self):
        # Пиксели области обработки
        return crop_pixels(self.rows, self.region())  # вырезаем область

    def require_image(self):
        # Проверка, что картинка есть
        if self.rows is None:  # картинки нет
            self.set_status("Сначала загрузите изображение")  # подсказка
            return False  # продолжить нельзя
        return True  # можно работать

    def remember(self):
        # Запоминаем состояние для отмены
        self.history.append((self.width, self.height, copy_pixels(self.rows)))  # копия пикселей
        if len(self.history) > HISTORY_LIMIT:  # история не бесконечна
            self.history.pop(0)  # убираем самый старый шаг

    def apply_to_region(self, transform):
        # Преобразование применяется к выделению или ко всей картинке
        if not self.require_image():  # картинки нет
            return False  # выходим
        x1, y1, x2, y2 = self.region()  # границы области
        part = transform(crop_pixels(self.rows, (x1, y1, x2, y2)))  # обрабатываем копию области
        self.remember()  # сохраняем шаг для отмены
        result = []  # новые строки картинки
        for y in range(self.height):  # по всем строкам
            if y1 <= y < y2:  # строка попадает в область
                result.append(self.rows[y][:x1] + part[y - y1] + self.rows[y][x2:])  # склеиваем строку
            else:  # строка вне области
                result.append(self.rows[y])  # оставляем как была
        self.set_pixels(self.width, self.height, result)  # ставим новые пиксели
        self.refresh()  # обновляем экран
        return True  # всё получилось

    def refresh(self):
        # Обновление картинки, статистики и гистограммы
        self.show_image()  # картинка на холсте
        self.update_statistics()  # характеристики внизу
        if self.hist_shown.get():  # график на экране
            self.draw_histogram()  # перерисовываем график

    def show_image(self):
        # Показ картинки на холсте
        if self.rows is None:  # картинки нет
            self.canvas.delete("all")  # чистим холст
            self.canvas.create_text(self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2,
                                    text="Загрузите изображение", fill="#888", font=("Segoe UI", 14))  # подсказка
            return  # больше нечего рисовать
        width = self.canvas.winfo_width()  # ширина холста
        height = self.canvas.winfo_height()  # высота холста
        if width < 20 or height < 20:  # холст ещё не разложен
            return  # ждём следующего события
        if self.pil_image is None:  # кэш пуст
            self.pil_image = pixels_to_image(self.width, self.height, self.rows)  # собираем картинку
        self.scale = min(width / self.width, height / self.height, 4.0)  # вписываем картинку в холст
        size = (max(1, int(self.width * self.scale)), max(1, int(self.height * self.scale)))  # размер на экране
        resample = Image.NEAREST if self.scale > 1 else Image.LANCZOS  # фильтр масштаба показа
        shown = self.pil_image.resize(size, resample)  # масштаб только для экрана
        self.photo = ImageTk.PhotoImage(shown)  # картинка для холста
        self.shift = ((width - size[0]) // 2, (height - size[1]) // 2)  # центрируем картинку
        self.canvas.delete("all")  # чистим холст
        self.canvas.create_image(self.shift[0], self.shift[1], anchor="nw", image=self.photo)  # ставим картинку
        self.draw_selection()  # рисуем рамку выделения

    def draw_selection(self):
        # Рамка выделения на холсте
        self.canvas.delete("selection")  # убираем старую рамку
        if self.selection is None:  # выделения нет
            return  # рисовать нечего
        x1, y1, x2, y2 = self.selection  # область в пикселях
        left = self.shift[0] + x1 * self.scale  # левый край на холсте
        top = self.shift[1] + y1 * self.scale  # верхний край на холсте
        right = self.shift[0] + x2 * self.scale  # правый край на холсте
        bottom = self.shift[1] + y2 * self.scale  # нижний край на холсте
        self.canvas.create_rectangle(left, top, right, bottom, outline="#ffcc00", width=2, dash=(6, 4), tags="selection")  # рамка

    def canvas_to_image(self, x, y):
        # Координаты холста в координаты пикселей
        image_x = int((x - self.shift[0]) / self.scale)  # столбец картинки
        image_y = int((y - self.shift[1]) / self.scale)  # строка картинки
        return image_x, image_y  # пара координат

    def on_mouse_press(self, event):
        # Начало выделения мышью
        if self.rows is None:  # картинки нет
            return  # выделять нечего
        self.drag_start = (event.x, event.y)  # запоминаем точку нажатия
        self.canvas.delete("rubber")  # убираем прошлую рамку

    def on_mouse_drag(self, event):
        # Протяжка рамки выделения
        if self.drag_start is None:  # нажатия не было
            return  # ничего не делаем
        self.canvas.delete("rubber")  # старая рамка
        self.canvas.create_rectangle(self.drag_start[0], self.drag_start[1], event.x, event.y,
                                     outline="#e04b4b", dash=(5, 3), width=2, tags="rubber")  # новая рамка

    def on_mouse_release(self, event):
        # Конец выделения
        if self.drag_start is None:  # нажатия не было
            return  # ничего не делаем
        x1, y1 = self.canvas_to_image(self.drag_start[0], self.drag_start[1])  # начало в пикселях
        x2, y2 = self.canvas_to_image(event.x, event.y)  # конец в пикселях
        self.drag_start = None  # протяжка закончена
        x1 = max(0, min(x1, self.width))  # не выходим влево
        x2 = max(0, min(x2, self.width))  # не выходим вправо
        y1 = max(0, min(y1, self.height))  # не выходим вверх
        y2 = max(0, min(y2, self.height))  # не выходим вниз
        if x1 > x2:  # точки наоборот
            x1, x2 = x2, x1  # меняем местами
        if y1 > y2:  # точки наоборот
            y1, y2 = y2, y1  # меняем местами
        if x2 - x1 < MIN_SELECTION or y2 - y1 < MIN_SELECTION:  # область слишком мала
            self.selection = None  # считаем, что выделения нет
            self.set_status("Выделение снято")  # сообщение
        else:  # область подходит
            self.selection = (x1, y1, x2, y2)  # запоминаем область
            self.set_status(f"Выделено {x2 - x1} x {y2 - y1} пикселей")  # сообщение
        self.refresh()  # перерисовываем

    def clear_selection(self):
        # Снятие выделения
        self.selection = None  # области нет
        self.refresh()  # перерисовываем
        self.set_status("Выделение снято")  # сообщение

    def toggle_histogram(self):
        # Показ и скрытие гистограммы
        if self.hist_shown.get():  # галочка стоит
            self.hist_frame.grid()  # показываем панель
            self.after(30, self.draw_histogram)  # рисуем после разметки
        else:  # галочка снята
            self.hist_frame.grid_remove()  # скрываем панель

    def draw_histogram(self):
        # Столбчатая гистограмма яркости
        canvas = self.hist_canvas  # холст графика
        canvas.delete("all")  # чистим график
        self.hist_info = None  # подсказка пока не нужна
        self.hist_level = None  # уровень сбрасываем
        if self.rows is None:  # картинки нет
            return  # рисовать нечего
        width = canvas.winfo_width()  # ширина графика
        height = canvas.winfo_height()  # высота графика
        if width < 50 or height < 40:  # график не разложен
            return  # ждём события
        hist = histogram(self.region_rows())  # яркость области
        peak = max(hist)  # самый частый уровень
        if peak == 0:  # пустая область
            return  # рисовать нечего
        chart = height - 18  # линия основания столбиков
        top = 14  # место под подпись максимума
        step = width / 256  # ширина одного столбика
        for level in range(256):  # по уровням яркости
            if hist[level] == 0:  # уровень не встречается
                continue  # пропускаем
            left = int(level * step)  # левая граница столбика
            right = int((level + 1) * step) + 1  # правая граница без щели
            bar = max(1, int(hist[level] / peak * (chart - top - 2)))  # высота столбика
            canvas.create_rectangle(left, chart - bar, right, chart, fill="#4a7ebb", outline="")  # столбик
        canvas.create_line(0, chart, width, chart, fill="#888")  # ось яркости
        canvas.create_text(4, 2, text=f"макс. {peak}", anchor="nw", fill="#666", font=("Segoe UI", 7))  # подпись шкалы
        for level in (0, 64, 128, 192, 255):  # подписи оси
            x = min(max(level * step, 12), width - 12)  # место подписи
            canvas.create_text(x, chart + 9, text=str(level), fill="#666", font=("Segoe UI", 7))  # уровень яркости
        self.hist_info = (hist, peak, step, chart, top)  # запоминаем для подсказки

    def hide_tip(self):
        # Убираем подсказку с графика
        self.hist_canvas.delete("tip")  # чистим подсказку

    def on_hist_leave(self, event):
        # Курсор ушёл с графика
        self.hide_tip()  # убираем подсказку
        self.hist_level = None  # уровень сбрасываем

    def on_hist_motion(self, event):
        # Подсказка при наведении на столбик
        canvas = self.hist_canvas  # холст графика
        if self.hist_info is None:  # графика нет
            return  # выходим
        hist, peak, step, chart, top = self.hist_info  # данные графика
        level = int(event.x / step)  # уровень под курсором
        level = max(0, min(level, 255))  # не выходим за диапазон
        if event.y > chart or hist[level] == 0:  # мимо столбика
            self.hide_tip()  # убираем подсказку
            self.hist_level = None  # уровень сбрасываем
            return  # выходим
        if level == self.hist_level:  # столбик тот же
            return  # не перерисовываем
        self.hist_level = level  # запоминаем уровень
        canvas.delete("tip")  # убираем прошлую подсказку
        bar = max(1, int(hist[level] / peak * (chart - top - 2)))  # высота столбика
        left = int(level * step)  # левая граница столбика
        right = int((level + 1) * step) + 1  # правая граница столбика
        canvas.create_rectangle(left, chart - bar, right, chart, outline="#c0392b", fill="", tags="tip")  # подсветка столбика
        total = sum(hist)  # всего пикселей
        percent = hist[level] * 100 / total if total else 0  # доля пикселей
        text = f"яркость {level}: {hist[level]} пикс. ({percent:.1f} %)"  # текст подсказки
        item = canvas.create_text(0, 0, text=text, anchor="nw", font=("Segoe UI", 8), fill="#222", tags="tip")  # текст
        box = canvas.bbox(item)  # границы текста
        width = box[2] - box[0]  # ширина текста
        height = box[3] - box[1]  # высота текста
        x = event.x + 12  # ставим справа от курсора
        y = event.y + 12  # ставим ниже курсора
        if x + width + 10 > canvas.winfo_width():  # не влезает справа
            x = event.x - width - 16  # ставим слева
        if y + height + 12 > chart:  # налезает на подписи оси
            y = event.y - height - 12  # ставим выше курсора
        x = max(2, x)  # не выходим влево
        y = max(2, y)  # не выходим вверх
        canvas.coords(item, x, y)  # переносим текст
        box = canvas.bbox(item)  # новые границы текста
        frame = canvas.create_rectangle(box[0] - 5, box[1] - 3, box[2] + 5, box[3] + 3,
                                        fill="#fffbe6", outline="#999", tags="tip")  # рамка подсказки
        canvas.tag_lower(frame, item)  # рамка под текстом

    def update_statistics(self):
        # Характеристики яркости в нижней строке
        if self.rows is None:  # картинки нет
            self.stats_label.config(text="Изображение не загружено")  # пустая строка
            return  # выходим
        stats = statistics(self.region_rows())  # считаем характеристики
        if stats is None:  # пустая область
            self.stats_label.config(text="Пустая область")  # сообщение
            return  # выходим
        kind = "выделение" if self.selection else "всё изображение"  # что считаем
        text = (f"{kind}: мин {stats['min']}  макс {stats['max']}  "
                f"среднее {stats['mean']:.2f}  дисперсия {stats['variance']:.1f}  "
                f"СКО {stats['std']:.2f}  медиана {stats['median']}  "
                f"мода {stats['mode']}  энтропия {stats['entropy']:.2f} бит")  # строка характеристик
        self.stats_label.config(text=text)  # выводим

    def load_pixels(self, width, height, rows, name):
        # Новая картинка в программе
        self.set_pixels(width, height, rows)  # рабочие пиксели
        self.original = copy_pixels(rows)  # копия для возврата
        self.history = []  # историю очищаем
        self.selection = None  # выделение сбрасываем
        self.refresh()  # обновляем экран
        self.set_status(f"Загружено: {name} ({width} x {height})")  # сообщение

    def open_path(self, path):
        # Чтение картинки из файла
        try:  # файл может не открыться
            with Image.open(path) as image:  # файл только читаем
                width, height, rows, small = read_image(image)  # получаем копию пикселей
        except Exception as error:  # ошибка чтения
            messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{error}")  # сообщение
            return  # выходим
        self.load_pixels(width, height, rows, os.path.basename(path))  # ставим картинку
        if small:  # копия была уменьшена
            self.set_status(f"Изображение уменьшено до {width} x {height} для обработки")  # пояснение

    def load_file(self):
        # Загрузка из файла
        path = filedialog.askopenfilename(title="Выберите изображение", filetypes=IMAGE_TYPES)  # диалог выбора
        if not path:  # пользователь отказался
            return  # выходим
        self.open_path(path)  # читаем файл

    def load_clipboard(self):
        # Загрузка из буфера обмена
        try:  # буфер может быть недоступен
            data = ImageGrab.grabclipboard()  # берём содержимое буфера
        except Exception as error:  # ошибка чтения
            messagebox.showerror("Ошибка", f"Не удалось прочитать буфер:\n{error}")  # сообщение
            return  # выходим
        if data is None:  # в буфере нет картинки
            messagebox.showinfo("Буфер обмена", "В буфере нет изображения")  # сообщение
            return  # выходим
        if isinstance(data, list):  # в буфере список файлов
            self.open_path(data[0])  # берём первый файл
            return  # выходим
        width, height, rows, small = read_image(data)  # пиксели из картинки буфера
        self.load_pixels(width, height, rows, "буфер обмена")  # ставим картинку
        if small:  # копия была уменьшена
            self.set_status(f"Изображение уменьшено до {width} x {height} для обработки")  # пояснение

    def save_file(self):
        # Сохранение копии в новый файл
        if not self.require_image():  # картинки нет
            return  # выходим
        path = filedialog.asksaveasfilename(title="Сохранить изображение", defaultextension=".png",
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("BMP", "*.bmp")])  # папка и имя
        if not path:  # пользователь отказался
            return  # выходим
        image = pixels_to_image(self.width, self.height, self.rows)  # картинка из пикселей
        try:  # запись может не удаться
            if path.lower().endswith((".jpg", ".jpeg")):  # для JPEG нужно качество
                image.save(path, quality=95)  # сохраняем с качеством
            else:  # остальные форматы
                image.save(path)  # сохраняем как есть
        except Exception as error:  # ошибка записи
            messagebox.showerror("Ошибка", f"Не удалось сохранить:\n{error}")  # сообщение
            return  # выходим
        self.set_status(f"Сохранено: {path}")  # сообщение

    def copy_clipboard(self):
        # Копирование картинки в буфер
        if not self.require_image():  # картинки нет
            return  # выходим
        try:  # буфер может быть занят
            copy_to_clipboard(self.width, self.height, self.rows)  # кладём картинку
        except Exception as error:  # ошибка буфера
            messagebox.showerror("Ошибка", f"Не удалось скопировать:\n{error}")  # сообщение
            return  # выходим
        self.set_status("Изображение скопировано в буфер обмена")  # сообщение

    def reset_image(self):
        # Возврат к загруженной картинке
        if self.original is None:  # картинки не было
            self.set_status("Сначала загрузите изображение")  # подсказка
            return  # выходим
        self.set_pixels(self.width, self.height, copy_pixels(self.original))  # копия исходных пикселей
        self.history = []  # историю очищаем
        self.selection = None  # выделение сбрасываем
        self.refresh()  # обновляем экран
        self.set_status("Возврат к загруженному изображению")  # сообщение

    def undo(self):
        # Отмена последнего шага
        if not self.history:  # история пуста
            self.set_status("Отменять нечего")  # сообщение
            return  # выходим
        width, height, rows = self.history.pop()  # прошлое состояние
        self.set_pixels(width, height, rows)  # ставим его
        self.selection = None  # выделение сбрасываем
        self.refresh()  # обновляем экран
        self.set_status("Шаг отменён")  # сообщение

    def do_brightness(self):
        # Преобразование яркости
        delta = int(self.bright_scale.get())  # добавка к яркости
        if delta == 0:  # менять нечего
            self.set_status("Сдвиг яркости равен нулю")  # сообщение
            return  # выходим
        if not self.apply_to_region(lambda part: change_brightness(part, delta)):  # обрабатываем область
            return  # картинки нет
        self.set_status(f"Яркость изменена на {delta:+d}")  # сообщение

    def do_contrast(self):
        # Преобразование контрастности
        percent = int(self.contrast_scale.get())  # отклонение от ста процентов
        if percent == 0:  # менять нечего
            self.set_status("Контраст не менялся")  # сообщение
            return  # выходим
        factor = 1 + percent / 100  # коэффициент контраста
        if not self.apply_to_region(lambda part: change_contrast(part, factor)):  # обрабатываем область
            return  # картинки нет
        self.set_status(f"Контраст: коэффициент {factor:.2f}")  # сообщение

    def do_gray(self):
        # Переход к оттенкам серого
        method = self.gray_method.get()  # выбранный способ
        if not self.apply_to_region(lambda part: to_gray(part, method)):  # обрабатываем область
            return  # картинки нет
        self.set_status(f"Оттенки серого: {method.lower()}")  # сообщение

    def do_negative(self):
        # Получение негатива
        if not self.apply_to_region(make_negative):  # обрабатываем область
            return  # картинки нет
        self.set_status("Получен негатив")  # сообщение

    def do_binarize(self):
        # Бинаризация области
        if not self.require_image():  # картинки нет
            return  # выходим
        method = self.bin_method.get()  # способ выбора порога
        if method == "Порог (вручную)":  # порог задаёт пользователь
            threshold = int(self.threshold_scale.get())  # берём со шкалы
        else:  # порог считаем автоматически
            hist = histogram(self.region_rows())  # гистограмма области
            if method == "Оцу":  # порог по Оцу
                threshold = otsu_threshold(hist)  # считаем порог
            elif method == "Средняя яркость":  # по среднему
                threshold = mean_threshold(hist)  # считаем порог
            else:  # по медиане
                threshold = median_threshold(hist)  # считаем порог
            self.threshold_scale.set(threshold)  # показываем порог на шкале
        if not self.apply_to_region(lambda part: binarize(part, threshold)):  # обрабатываем область
            return  # картинки нет
        self.set_status(f"Бинаризация, порог {threshold}")  # сообщение

    def do_equalize(self):
        # Выравнивание гистограммы
        if not self.apply_to_region(equalize):  # обрабатываем область
            return  # картинки нет
        self.set_status("Гистограмма выровнена")  # сообщение

    def do_stretch(self):
        # Растяжение гистограммы
        if not self.apply_to_region(stretch):  # обрабатываем область
            return  # картинки нет
        self.set_status("Гистограмма растянута")  # сообщение

    def update_scrollbar(self):
        # Полоса прокрутки показывается только при нехватке места
        need = self.panel_frame.winfo_reqheight() > self.panel_canvas.winfo_height()  # блоки выше панели
        if need and not self.panel_scroll.winfo_ismapped():  # места мало
            self.panel_scroll.grid()  # показываем полосу
        elif not need and self.panel_scroll.winfo_ismapped():  # всё помещается
            self.panel_scroll.grid_remove()  # скрываем полосу

    def on_panel_configure(self, event):
        # Высота прокручиваемой области
        self.panel_canvas.configure(scrollregion=self.panel_canvas.bbox("all"))  # все блоки целиком
        self.update_scrollbar()  # проверяем надобность полосы

    def on_panel_canvas(self, event):
        # Блоки растягиваются по ширине панели
        self.panel_canvas.itemconfigure(self.panel_window, width=event.width)  # ширина рамки
        self.update_scrollbar()  # проверяем надобность полосы

    def on_wheel(self, event):
        # Прокрутка панели колесом мыши
        widget = event.widget  # виджет под курсором
        while widget is not None:  # идём по родителям
            if widget is self.panel_canvas:  # курсор над панелью
                self.panel_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")  # крутим панель
                return  # прокрутка сделана
            widget = widget.master  # поднимаемся выше

    def on_resize(self, event):
        # Перерисовка при изменении размера окна
        if event.widget is not self:  # интересует только окно
            return  # выходим
        size = (self.canvas.winfo_width(), self.canvas.winfo_height())  # размер холста
        if size == self.last_size:  # размер не изменился
            return  # выходим
        self.last_size = size  # запоминаем размер
        self.show_image()  # перерисовываем картинку
        if self.hist_shown.get():  # график на экране
            self.draw_histogram()  # обновляем график


def main():
    # Запуск программы
    app = ImageEditor()  # создаём окно
    app.mainloop()  # цикл событий


if __name__ == "__main__":
    main()
