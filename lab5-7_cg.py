# Подключение модулей
import ctypes  # вызовы функций Windows
import math  # логарифм, корень, косинус
import os  # имя файла без пути
import random  # случайный шум
import struct  # сборка заголовка DIB
import time  # замер времени фильтрации
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


def put_pixel(rows, x, y, color):
    # Пиксель ставится только внутри области
    if 0 <= y < len(rows) and 0 <= x < len(rows[0]):  # координаты внутри
        rows[y][x] = list(color)  # записываем цвет


def draw_line(rows, x1, y1, x2, y2, color):
    # Отрезок по алгоритму Брезенхема
    dx = abs(x2 - x1)  # шаг по X
    dy = -abs(y2 - y1)  # шаг по Y
    sx = 1 if x1 < x2 else -1  # направление по X
    sy = 1 if y1 < y2 else -1  # направление по Y
    error = dx + dy  # начальная ошибка
    while True:  # идём по точкам
        put_pixel(rows, x1, y1, color)  # ставим точку
        if x1 == x2 and y1 == y2:  # дошли до конца
            break  # выходим
        double = 2 * error  # удвоенная ошибка
        if double >= dy:  # шаг по X
            error += dy  # правим ошибку
            x1 += sx  # сдвиг по X
        if double <= dx:  # шаг по Y
            error += dx  # правим ошибку
            y1 += sy  # сдвиг по Y


def draw_circle(rows, cx, cy, radius, color):
    # Окружность по алгоритму средней точки
    x = radius  # смещение по X
    y = 0  # смещение по Y
    error = 0  # ошибка
    while x >= y:  # проходим восьмую часть
        put_pixel(rows, cx + x, cy + y, color)  # точка 1
        put_pixel(rows, cx + y, cy + x, color)  # точка 2
        put_pixel(rows, cx - y, cy + x, color)  # точка 3
        put_pixel(rows, cx - x, cy + y, color)  # точка 4
        put_pixel(rows, cx - x, cy - y, color)  # точка 5
        put_pixel(rows, cx - y, cy - x, color)  # точка 6
        put_pixel(rows, cx + y, cy - x, color)  # точка 7
        put_pixel(rows, cx + x, cy - y, color)  # точка 8
        y += 1  # поднимаемся
        if error <= 0:  # ошибка внутри
            error += 2 * y + 1  # правим
        if error > 0:  # ошибка снаружи
            x -= 1  # сужаем
            error -= 2 * x + 1  # правим


def add_noise(rows, kind, amount, size, colored):
    # Искусственный шум на копии области
    result = copy_pixels(rows)  # копия под шум
    height = len(rows)  # высота области
    width = len(rows[0])  # ширина области
    for _ in range(amount):  # по числу объектов
        if colored:  # цветной шум
            color = [random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)]  # случайный цвет
        else:  # чёрно-белый шум
            value = 255 if random.random() < 0.5 else 0  # белая или чёрная точка
            color = [value, value, value]  # серый оттенок
        x = random.randrange(width)  # центр по X
        y = random.randrange(height)  # центр по Y
        if kind == "Точки":  # квадратная точка
            for dy in range(size):  # по высоте точки
                for dx in range(size):  # по ширине точки
                    put_pixel(result, x + dx, y + dy, color)  # ставим пиксель
        elif kind == "Линии":  # отрезок под углом
            angle = random.uniform(0, 2 * math.pi)  # случайный угол
            length = size * 8  # длина отрезка
            draw_line(result, x, y, int(x + length * math.cos(angle)), int(y + length * math.sin(angle)), color)  # линия
        else:  # окружность
            draw_circle(result, x, y, size, color)  # кольцо радиуса size
    return result  # готовые пиксели


def uniform_filter(rows, radius):
    # Равномерный фильтр: среднее по окну
    height = len(rows)  # высота области
    width = len(rows[0])  # ширина области
    size = 2 * radius + 1  # сторона окна
    padded = []  # строки с повторёнными краями
    for row in rows:  # по строкам
        padded.append([row[0]] * radius + row + [row[-1]] * radius)  # поля слева и справа
    horizontal = []  # результат по строкам
    for row in padded:  # по строкам
        line = []  # новая строка
        for x in range(width):  # по пикселям
            r = g = b = 0  # суммы каналов
            for dx in range(size):  # по окну
                pixel = row[x + dx]  # соседний пиксель
                r += pixel[0]  # красный
                g += pixel[1]  # зелёный
                b += pixel[2]  # синий
            line.append([r // size, g // size, b // size])  # среднее окна
        horizontal.append(line)  # добавляем строку
    vertical = [horizontal[0]] * radius + horizontal + [horizontal[-1]] * radius  # поля сверху и снизу
    result = []  # итоговые строки
    for y in range(height):  # по строкам
        line = []  # новая строка
        for x in range(width):  # по пикселям
            r = g = b = 0  # суммы каналов
            for dy in range(size):  # по окну
                pixel = vertical[y + dy][x]  # пиксель строки
                r += pixel[0]  # красный
                g += pixel[1]  # зелёный
                b += pixel[2]  # синий
            line.append([r // size, g // size, b // size])  # среднее окна
        result.append(line)  # готовая строка
    return result  # готовые пиксели


def median_filter(rows, radius):
    # Медианный фильтр: срединное значение окна
    height = len(rows)  # высота области
    width = len(rows[0])  # ширина области
    size = 2 * radius + 1  # сторона окна
    padded = []  # строки с полями по краям
    for row in rows:  # по строкам
        padded.append([row[0]] * radius + row + [row[-1]] * radius)  # поля слева и справа
    vertical = [padded[0]] * radius + padded + [padded[-1]] * radius  # поля сверху и снизу
    middle = size * size // 2  # номер срединного элемента
    result = []  # итоговые строки
    for y in range(height):  # по строкам
        line = []  # новая строка
        for x in range(width):  # по пикселям
            red = []  # красные каналы окна
            green = []  # зелёные каналы окна
            blue = []  # синие каналы окна
            for dy in range(size):  # по строкам окна
                part = vertical[y + dy][x:x + size]  # пиксели строки окна
                for pixel in part:  # по пикселям окна
                    red.append(pixel[0])  # красный
                    green.append(pixel[1])  # зелёный
                    blue.append(pixel[2])  # синий
            red.sort()  # сортируем красные
            green.sort()  # сортируем зелёные
            blue.sort()  # сортируем синие
            line.append([red[middle], green[middle], blue[middle]])  # медиана каналов
        result.append(line)  # готовая строка
    return result  # готовые пиксели


def sharpen_kernel(rows, strength):
    # Повышение резкости ядром 3 x 3
    height = len(rows)  # высота области
    width = len(rows[0])  # ширина области
    k = strength / 2  # сила ядра
    center = 1 + k  # вес центрального пикселя
    side = -k / 8  # вес соседей
    padded = []  # строки с полями по краям
    for row in rows:  # по строкам
        padded.append([row[0]] + row + [row[-1]])  # поля слева и справа
    padded = [padded[0]] + padded + [padded[-1]]  # поля сверху и снизу
    result = []  # итоговые строки
    for y in range(height):  # по строкам
        line = []  # новая строка
        for x in range(width):  # по пикселям
            r = g = b = 0.0  # суммы каналов
            for dy in range(3):  # по строкам окна
                part = padded[y + dy][x:x + 3]  # три пикселя строки
                for dx in range(3):  # по столбцам окна
                    pixel = part[dx]  # пиксель окна
                    weight = center if (dy == 1 and dx == 1) else side  # вес пикселя
                    r += pixel[0] * weight  # красный
                    g += pixel[1] * weight  # зелёный
                    b += pixel[2] * weight  # синий
            line.append([clamp(r), clamp(g), clamp(b)])  # новые значения
        result.append(line)  # готовая строка
    return result  # готовые пиксели


def unsharp_mask(rows, strength):
    # Маска нерезкости: исходное плюс разница с размытым
    soft = uniform_filter(rows, 1)  # размытая копия
    result = []  # итоговые строки
    for y in range(len(rows)):  # по строкам
        line = []  # новая строка
        for x in range(len(rows[0])):  # по пикселям
            src = rows[y][x]  # исходный пиксель
            blur = soft[y][x]  # размытый пиксель
            line.append([clamp(src[0] + strength * (src[0] - blur[0])),
                         clamp(src[1] + strength * (src[1] - blur[1])),
                         clamp(src[2] + strength * (src[2] - blur[2]))])  # усиливаем разницу
        result.append(line)  # готовая строка
    return result  # готовые пиксели


def emboss(rows, depth):
    # Тиснение: сглаживание, затем рельеф по перепаду яркости
    smooth = uniform_filter(rows, 1)  # сглаживаем перед тиснением
    height = len(smooth)  # высота области
    width = len(smooth[0])  # ширина области
    kernel = [[0, -1, 0], [-1, 0, 1], [0, 1, 0]]  # ядро тиснения
    strength = depth / 2  # коэффициент рельефа
    padded = []  # строки с полями по краям
    for row in smooth:  # по строкам
        padded.append([row[0]] + row + [row[-1]])  # поля слева и справа
    padded = [padded[0]] + padded + [padded[-1]]  # поля сверху и снизу
    result = []  # итоговые строки
    for y in range(height):  # по строкам
        line = []  # новая строка
        for x in range(width):  # по пикселям
            total = 0  # сумма по ядру
            for dy in range(3):  # по строкам окна
                part = padded[y + dy][x:x + 3]  # три пикселя строки
                for dx in range(3):  # по столбцам окна
                    weight = kernel[dy][dx]  # вес пикселя
                    if weight:  # нулевые можно пропустить
                        pixel = part[dx]  # пиксель окна
                        total += weight * brightness_of(pixel[0], pixel[1], pixel[2])  # вклад пикселя
            value = clamp(128 + strength * total)  # сдвигаем к среднему серому
            line.append([value, value, value])  # серый пиксель
        result.append(line)  # готовая строка
    return result  # готовые пиксели


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


class ScrollPage(ttk.Frame):
    # Страница вкладки с вертикальной прокруткой
    def __init__(self, master):
        super().__init__(master)  # создаём страницу
        self.rowconfigure(0, weight=1)  # холст тянется по высоте
        self.columnconfigure(0, weight=1)  # холст тянется по ширине
        self.canvas = tk.Canvas(self, width=272, highlightthickness=0)  # холст прокрутки
        self.canvas.grid(row=0, column=0, sticky="nsew")  # место холста
        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)  # полоса прокрутки
        self.scroll.grid(row=0, column=1, sticky="ns")  # справа от холста
        self.canvas.configure(yscrollcommand=self.scroll.set)  # связываем полосу и холст
        self.body = ttk.Frame(self.canvas)  # рамка с блоками
        self.body.columnconfigure(0, weight=1)  # блоки по ширине страницы
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")  # рамка на холсте
        self.body.bind("<Configure>", self.on_body)  # следим за высотой блоков
        self.canvas.bind("<Configure>", self.on_canvas)  # следим за шириной страницы

    def on_body(self, event):
        # Высота прокрутки по содержимому
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))  # все блоки целиком
        self.update_scrollbar()  # проверяем надобность полосы

    def on_canvas(self, event):
        # Блоки растягиваются по ширине страницы
        self.canvas.itemconfigure(self.window, width=event.width)  # ширина рамки
        self.update_scrollbar()  # проверяем надобность полосы

    def update_scrollbar(self):
        # Полоса показывается только при нехватке места
        need = self.body.winfo_reqheight() > self.canvas.winfo_height()  # блоки выше страницы
        if need and not self.scroll.winfo_ismapped():  # места мало
            self.scroll.grid()  # показываем полосу
        elif not need and self.scroll.winfo_ismapped():  # всё помещается
            self.scroll.grid_remove()  # скрываем полосу


class ImageEditor(tk.Tk):
    # Главное окно программы
    def __init__(self):
        super().__init__()  # создаём окно
        self.title("Коррекция фотоизображения")  # заголовок окна
        self.geometry("1180x820")  # стартовый размер окна
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
        # Левая колонка с общими кнопками и вкладками
        left = ttk.Frame(self, padding=(10, 8, 0, 0))  # контейнер левой части
        left.grid(row=0, column=0, sticky="ns")  # ставим слева
        left.rowconfigure(1, weight=1)  # вкладки тянутся по высоте
        self.build_file_box(left)  # блок загрузки и сохранения
        self.notebook = ttk.Notebook(left)  # вкладки с инструментами
        self.notebook.grid(row=1, column=0, sticky="nsew", pady=(6, 0))  # место вкладок
        self.page_correction = ScrollPage(self.notebook)  # страница коррекции
        self.page_filter = ScrollPage(self.notebook)  # страница фильтрации
        self.notebook.add(self.page_correction, text=" Коррекция ")  # первая вкладка
        self.notebook.add(self.page_filter, text=" Фильтрация ")  # вторая вкладка
        self.pages = [self.page_correction, self.page_filter]  # прокручиваемые страницы
        self.build_correction(self.page_correction.body)  # блоки коррекции
        self.build_filters(self.page_filter.body)  # блоки фильтрации
        self.build_view()  # картинка и гистограмма
        self.build_bottom()  # статистика и сообщения
        self.bind_all("<MouseWheel>", self.on_wheel)  # колесо мыши крутит страницы
        self.rowconfigure(0, weight=1)  # верхняя часть растягивается
        self.columnconfigure(1, weight=1)  # правая часть растягивается

    def build_file_box(self, parent):
        # Блок загрузки и сохранения
        box = ttk.LabelFrame(parent, text="Файл", padding=5)  # рамка блока
        box.grid(row=0, column=0, sticky="ew")  # место в колонке
        box.columnconfigure(0, weight=1)  # первая колонка кнопок
        box.columnconfigure(1, weight=1)  # вторая колонка кнопок
        ttk.Button(box, text="Из файла", command=self.load_file).grid(row=0, column=0, sticky="ew", padx=1, pady=1)  # загрузка файла
        ttk.Button(box, text="Из буфера", command=self.load_clipboard).grid(row=0, column=1, sticky="ew", padx=1, pady=1)  # загрузка из буфера
        ttk.Button(box, text="В файл", command=self.save_file).grid(row=1, column=0, sticky="ew", padx=1, pady=1)  # сохранение копии
        ttk.Button(box, text="В буфер", command=self.copy_clipboard).grid(row=1, column=1, sticky="ew", padx=1, pady=1)  # копия в буфер
        ttk.Button(box, text="К исходному", command=self.reset_image).grid(row=2, column=0, sticky="ew", padx=1, pady=1)  # возврат к загруженному
        ttk.Button(box, text="Отменить", command=self.undo).grid(row=2, column=1, sticky="ew", padx=1, pady=1)  # шаг назад

    def build_correction(self, panel):
        # Блок выделения области
        sel_box = ttk.LabelFrame(panel, text="Выделение", padding=5)  # рамка блока
        sel_box.grid(row=0, column=0, sticky="ew", pady=2)  # место в панели
        sel_box.columnconfigure(0, weight=1)  # одна колонка
        ttk.Button(sel_box, text="Снять выделение", command=self.clear_selection).grid(row=0, column=0, sticky="ew")  # сброс области
        ttk.Label(sel_box, text="Протяните мышью по картинке", foreground="#666").grid(row=1, column=0, sticky="w", pady=(2, 0))  # подсказка
        ttk.Label(sel_box, text="преобразования идут по выделению", foreground="#666").grid(row=2, column=0, sticky="w")  # уточнение

        # Блок яркости
        bright_box = ttk.LabelFrame(panel, text="Яркость (сдвиг)", padding=5)  # рамка блока
        bright_box.grid(row=1, column=0, sticky="ew", pady=2)  # место в панели
        bright_box.columnconfigure(0, weight=1)  # одна колонка
        self.bright_scale = tk.Scale(bright_box, from_=-100, to=100, orient="horizontal", resolution=1)  # ползунок сдвига
        self.bright_scale.grid(row=0, column=0, sticky="ew")  # место ползунка
        ttk.Button(bright_box, text="Применить", command=self.do_brightness).grid(row=1, column=0, sticky="ew", pady=(2, 0))  # запуск

        # Блок контрастности
        contrast_box = ttk.LabelFrame(panel, text="Контрастность (сдвиг, %)", padding=5)  # рамка блока
        contrast_box.grid(row=2, column=0, sticky="ew", pady=2)  # место в панели
        contrast_box.columnconfigure(0, weight=1)  # одна колонка
        self.contrast_scale = tk.Scale(contrast_box, from_=-100, to=100, orient="horizontal", resolution=1)  # ползунок контраста
        self.contrast_scale.grid(row=0, column=0, sticky="ew")  # место ползунка
        ttk.Button(contrast_box, text="Применить", command=self.do_contrast).grid(row=1, column=0, sticky="ew", pady=(2, 0))  # запуск

        # Блок цветности
        color_box = ttk.LabelFrame(panel, text="Цветность", padding=5)  # рамка блока
        color_box.grid(row=3, column=0, sticky="ew", pady=2)  # место в панели
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
        hist_box.grid(row=4, column=0, sticky="ew", pady=2)  # место в панели
        hist_box.columnconfigure(0, weight=1)  # первая колонка
        hist_box.columnconfigure(1, weight=1)  # вторая колонка
        self.hist_shown = tk.BooleanVar(value=False)  # гистограмма скрыта
        ttk.Checkbutton(hist_box, text="Показать", variable=self.hist_shown, command=self.toggle_histogram).grid(row=0, column=0, columnspan=2, sticky="w")  # галочка показа
        ttk.Button(hist_box, text="Выровнять", command=self.do_equalize).grid(row=1, column=0, sticky="ew", padx=1, pady=2)  # выравнивание
        ttk.Button(hist_box, text="Растянуть", command=self.do_stretch).grid(row=1, column=1, sticky="ew", padx=1, pady=2)  # растяжение

    def build_filters(self, panel):
        # Подсказка про выделение
        ttk.Label(panel, text="Фильтры идут по выделению, если оно задано", foreground="#666").grid(row=0, column=0, sticky="w", padx=2, pady=(0, 2))  # пояснение

        # Блок искусственного шума
        noise_box = ttk.LabelFrame(panel, text="Шум", padding=5)  # рамка блока
        noise_box.grid(row=1, column=0, sticky="ew", pady=2)  # место в панели
        noise_box.columnconfigure(0, weight=1)  # колонка типа шума
        noise_box.columnconfigure(1, weight=0)  # колонка цвета
        self.noise_kind = tk.StringVar(value="Точки")  # тип шума
        ttk.Combobox(noise_box, textvariable=self.noise_kind, values=["Точки", "Линии", "Окружности"], state="readonly", width=11).grid(row=0, column=0, sticky="ew")  # выбор типа
        self.noise_color = tk.StringVar(value="Чёрно-белый")  # цвет шума
        ttk.Combobox(noise_box, textvariable=self.noise_color, values=["Чёрно-белый", "Цветной"], state="readonly", width=13).grid(row=0, column=1, sticky="e", padx=(3, 0))  # выбор цвета
        ttk.Label(noise_box, text="количество объектов", foreground="#666").grid(row=1, column=0, sticky="w", pady=(3, 0))  # подпись
        self.noise_amount = tk.Scale(noise_box, from_=1, to=200, orient="horizontal", resolution=1)  # ползунок количества
        self.noise_amount.set(60)  # начальное значение
        self.noise_amount.grid(row=2, column=0, sticky="ew")  # место ползунка
        ttk.Label(noise_box, text="размер объекта", foreground="#666").grid(row=3, column=0, sticky="w")  # подпись
        self.noise_size = tk.Scale(noise_box, from_=1, to=30, orient="horizontal", resolution=1)  # ползунок размера
        self.noise_size.set(8)  # начальное значение
        self.noise_size.grid(row=4, column=0, sticky="ew")  # место ползунка
        ttk.Button(noise_box, text="Наложить шум", command=self.do_noise).grid(row=5, column=0, sticky="ew", pady=(3, 0))  # запуск

        # Блок шумоподавления
        denoise_box = ttk.LabelFrame(panel, text="Шумоподавление", padding=5)  # рамка блока
        denoise_box.grid(row=2, column=0, sticky="ew", pady=2)  # место в панели
        denoise_box.columnconfigure(0, weight=1)  # первая колонка
        denoise_box.columnconfigure(1, weight=1)  # вторая колонка
        self.denoise_method = tk.StringVar(value="Равномерный")  # тип фильтра
        ttk.Combobox(denoise_box, textvariable=self.denoise_method, values=["Равномерный", "Медианный"], state="readonly").grid(row=0, column=0, columnspan=2, sticky="ew")  # выбор фильтра
        ttk.Label(denoise_box, text="апертура", foreground="#666").grid(row=1, column=0, sticky="w", pady=(3, 0))  # подпись
        self.aperture_size = tk.StringVar(value="3 x 3")  # размер окна
        ttk.Combobox(denoise_box, textvariable=self.aperture_size, values=["3 x 3", "5 x 5", "7 x 7", "9 x 9"], state="readonly", width=7).grid(row=1, column=1, sticky="e", pady=(3, 0))  # выбор апертуры
        ttk.Button(denoise_box, text="Применить", command=self.do_denoise).grid(row=2, column=0, sticky="ew", padx=(0, 2), pady=(4, 0))  # запуск
        ttk.Button(denoise_box, text="Сравнить", command=self.compare_denoise).grid(row=2, column=1, sticky="ew", padx=(2, 0), pady=(4, 0))  # сравнение

        # Блок резкости
        sharp_box = ttk.LabelFrame(panel, text="Резкость", padding=5)  # рамка блока
        sharp_box.grid(row=3, column=0, sticky="ew", pady=2)  # место в панели
        sharp_box.columnconfigure(0, weight=1)  # первая колонка
        sharp_box.columnconfigure(1, weight=1)  # вторая колонка
        self.sharpen_method = tk.StringVar(value="Ядро 3 x 3")  # способ повышения резкости
        ttk.Combobox(sharp_box, textvariable=self.sharpen_method, values=["Ядро 3 x 3", "Маска нерезкости"], state="readonly").grid(row=0, column=0, sticky="ew")  # выбор способа
        ttk.Label(sharp_box, text="сила", foreground="#666").grid(row=1, column=0, sticky="w", pady=(3, 0))  # подпись
        self.sharpen_scale = tk.Scale(sharp_box, from_=1, to=10, orient="horizontal", resolution=1)  # ползунок силы
        self.sharpen_scale.set(4)  # начальное значение
        self.sharpen_scale.grid(row=2, column=0, columnspan=2, sticky="ew")  # место ползунка
        ttk.Button(sharp_box, text="Применить", command=self.do_sharpen).grid(row=3, column=0, sticky="ew", padx=(0, 2), pady=(3, 0))  # запуск
        ttk.Button(sharp_box, text="Сравнить", command=self.compare_sharpen).grid(row=3, column=1, sticky="ew", padx=(2, 0), pady=(3, 0))  # сравнение

        # Блок тиснения
        emboss_box = ttk.LabelFrame(panel, text="Тиснение", padding=5)  # рамка блока
        emboss_box.grid(row=4, column=0, sticky="ew", pady=2)  # место в панели
        emboss_box.columnconfigure(0, weight=1)  # одна колонка
        ttk.Label(emboss_box, text="глубина", foreground="#666").grid(row=0, column=0, sticky="w")  # подпись
        self.emboss_scale = tk.Scale(emboss_box, from_=1, to=5, orient="horizontal", resolution=1)  # ползунок глубины
        self.emboss_scale.set(3)  # начальное значение
        self.emboss_scale.grid(row=1, column=0, sticky="ew")  # место ползунка
        ttk.Button(emboss_box, text="Применить", command=self.do_emboss).grid(row=2, column=0, sticky="ew", pady=(3, 0))  # запуск

    def build_view(self):
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

    def build_bottom(self):
        # Нижняя строка со статистикой
        bottom = ttk.Frame(self, padding=(10, 4))  # контейнер строки
        bottom.grid(row=1, column=0, columnspan=2, sticky="ew")  # место внизу
        bottom.columnconfigure(0, weight=1)  # текст по ширине
        self.stats_label = ttk.Label(bottom, text="Изображение не загружено", font=("Consolas", 9))  # характеристики
        self.stats_label.grid(row=0, column=0, sticky="w")  # слева
        self.status_label = ttk.Label(bottom, text="Готово", foreground="#666")  # сообщения
        self.status_label.grid(row=1, column=0, sticky="w")  # под характеристиками

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

    def set_busy(self, text):
        # Курсор ожидания и сообщение
        self.config(cursor="watch")  # курсор ожидания
        self.set_status(text)  # текст внизу
        self.update_idletasks()  # сразу показываем

    def set_ready(self, text):
        # Обычный курсор и итоговое сообщение
        self.config(cursor="")  # обычный курсор
        self.set_status(text)  # текст внизу

    def compare_crop(self):
        # Небольшой фрагмент области для сравнения
        x1, y1, x2, y2 = self.region()  # границы области
        width = min(400, x2 - x1)  # ширина фрагмента
        height = min(300, y2 - y1)  # высота фрагмента
        left = x1 + (x2 - x1 - width) // 2  # центрируем по X
        top = y1 + (y2 - y1 - height) // 2  # центрируем по Y
        return crop_pixels(self.rows, (left, top, left + width, top + height))  # вырезаем фрагмент

    def crop_note(self, rows):
        # Подпись фрагмента под картинкой
        return f"{len(rows[0])} x {len(rows)} пикс., фрагмент 1:1"  # размеры без масштаба

    def show_compare(self, title, items):
        # Окно сравнения нескольких вариантов
        window = tk.Toplevel(self)  # отдельное окно
        window.title(title)  # заголовок окна
        window.resizable(False, False)  # размер фиксирован
        frame = ttk.Frame(window, padding=10)  # контейнер вариантов
        frame.pack(fill="both", expand=True)  # место в окне
        window.photos = []  # ссылки на картинки
        for index, (caption, rows, note) in enumerate(items):  # по вариантам
            image = pixels_to_image(len(rows[0]), len(rows), rows)  # картинка варианта
            photo = ImageTk.PhotoImage(image)  # картинка для окна
            window.photos.append(photo)  # сохраняем ссылку
            ttk.Label(frame, text=caption, font=("Segoe UI", 9, "bold")).grid(row=0, column=index, padx=5, pady=(0, 4))  # подпись
            ttk.Label(frame, image=photo, relief="solid", borderwidth=1).grid(row=1, column=index, padx=5)  # картинка
            ttk.Label(frame, text=note, foreground="#666").grid(row=2, column=index, padx=5, pady=(3, 6))  # пояснение
        ttk.Button(frame, text="Закрыть", command=window.destroy).grid(row=3, column=0, columnspan=len(items), pady=(4, 0))  # закрытие
        window.update_idletasks()  # считаем размеры окна
        x = self.winfo_rootx() + (self.winfo_width() - window.winfo_width()) // 2  # центр по X
        y = self.winfo_rooty() + (self.winfo_height() - window.winfo_height()) // 3  # центр по Y
        window.geometry(f"+{max(0, x)}+{max(0, y)}")  # ставим окно

    def do_noise(self):
        # Наложение искусственного шума
        if not self.require_image():  # картинки нет
            return  # выходим
        kind = self.noise_kind.get()  # тип шума
        colored = self.noise_color.get() == "Цветной"  # цветной или чёрно-белый
        amount = int(self.noise_amount.get())  # число объектов
        size = int(self.noise_size.get())  # размер объекта
        self.apply_to_region(lambda part: add_noise(part, kind, amount, size, colored))  # обрабатываем область
        mode = "цветной" if colored else "ч/б"  # подпись режима
        self.set_status(f"Шум: {kind.lower()}, объектов {amount}, {mode}")  # сообщение

    def aperture_radius(self):
        # Радиус окна по выбранной апертуре
        return int(self.aperture_size.get().split()[0]) // 2  # половина стороны

    def do_denoise(self):
        # Шумоподавление выбранным фильтром
        if not self.require_image():  # картинки нет
            return  # выходим
        method = self.denoise_method.get()  # выбранный фильтр
        radius = self.aperture_radius()  # радиус окна
        size = 2 * radius + 1  # сторона окна
        self.set_busy(f"{method} фильтр {size} x {size}...")  # курсор ожидания
        start = time.perf_counter()  # начало замера
        if method == "Равномерный":  # равномерный фильтр
            self.apply_to_region(lambda part: uniform_filter(part, radius))  # обрабатываем область
        else:  # медианный фильтр
            self.apply_to_region(lambda part: median_filter(part, radius))  # обрабатываем область
        spent = time.perf_counter() - start  # время работы
        self.set_ready(f"{method} {size} x {size}: {spent:.1f} с")  # итог

    def compare_denoise(self):
        # Сравнение равномерного и медианного фильтров
        if not self.require_image():  # картинки нет
            return  # выходим
        radius = self.aperture_radius()  # радиус окна
        size = 2 * radius + 1  # сторона окна
        crop = self.compare_crop()  # фрагмент для сравнения
        self.set_busy("Считаем фильтры...")  # курсор ожидания
        start = time.perf_counter()  # начало замера
        box = uniform_filter(crop, radius)  # равномерный фильтр
        box_time = time.perf_counter() - start  # время равномерного
        start = time.perf_counter()  # новый замер
        med = median_filter(crop, radius)  # медианный фильтр
        med_time = time.perf_counter() - start  # время медианного
        self.set_ready("Сравнение готово")  # итог
        self.show_compare("Шумоподавление", [
            ("Исходное", crop, self.crop_note(crop)),  # без фильтра
            (f"Равномерный {size} x {size}", box, f"{box_time:.2f} с"),  # равномерный
            (f"Медианный {size} x {size}", med, f"{med_time:.2f} с"),  # медианный
        ])  # открываем окно

    def do_sharpen(self):
        # Повышение резкости выбранным способом
        if not self.require_image():  # картинки нет
            return  # выходим
        method = self.sharpen_method.get()  # выбранный способ
        strength = int(self.sharpen_scale.get())  # сила
        self.set_busy(f"Резкость: {method.lower()}...")  # курсор ожидания
        start = time.perf_counter()  # начало замера
        if method == "Ядро 3 x 3":  # повышение ядром
            self.apply_to_region(lambda part: sharpen_kernel(part, strength))  # обрабатываем область
        else:  # маска нерезкости
            self.apply_to_region(lambda part: unsharp_mask(part, strength / 2))  # обрабатываем область
        spent = time.perf_counter() - start  # время работы
        self.set_ready(f"Резкость, сила {strength}: {spent:.1f} с")  # итог

    def compare_sharpen(self):
        # Сравнение способов повышения резкости
        if not self.require_image():  # картинки нет
            return  # выходим
        strength = int(self.sharpen_scale.get())  # сила
        crop = self.compare_crop()  # фрагмент для сравнения
        self.set_busy("Считаем резкость...")  # курсор ожидания
        start = time.perf_counter()  # начало замера
        kernel = sharpen_kernel(crop, strength)  # по ядру
        kernel_time = time.perf_counter() - start  # время ядра
        start = time.perf_counter()  # новый замер
        mask = unsharp_mask(crop, strength / 2)  # по маске нерезкости
        mask_time = time.perf_counter() - start  # время маски
        self.set_ready("Сравнение готово")  # итог
        self.show_compare("Повышение резкости", [
            ("Исходное", crop, self.crop_note(crop)),  # без обработки
            ("Ядро 3 x 3", kernel, f"{kernel_time:.2f} с"),  # по ядру
            ("Маска нерезкости", mask, f"{mask_time:.2f} с"),  # по маске
        ])  # открываем окно

    def do_emboss(self):
        # Тиснение области
        if not self.require_image():  # картинки нет
            return  # выходим
        depth = int(self.emboss_scale.get())  # глубина рельефа
        self.set_busy("Тиснение...")  # курсор ожидания
        start = time.perf_counter()  # начало замера
        self.apply_to_region(lambda part: emboss(part, depth))  # обрабатываем область
        spent = time.perf_counter() - start  # время работы
        self.set_ready(f"Тиснение, глубина {depth}: {spent:.1f} с")  # итог

    def on_wheel(self, event):
        # Прокрутка страницы колесом мыши
        widget = event.widget  # виджет под курсором
        while widget is not None:  # идём по родителям
            for page in self.pages:  # по страницам вкладок
                if widget is page.canvas:  # курсор над страницей
                    page.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")  # крутим страницу
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
