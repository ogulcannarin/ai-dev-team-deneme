"""
Izole Calisma Alani - Hesaplama Modulu
Bu dosya Coder Agent tarafindan gorev kapsaminda otomatik uretilmistir.
"""

from typing import Union

Number = Union[int, float]


def add(a: Number, b: Number) -> Number:
    """Iki sayiyi toplar ve sonucu dondurur."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Toplama islemi icin gecerli sayisal degerler girilmelidir.")
    return a + b


def subtract(a: Number, b: Number) -> Number:
    """Iki sayinin farkini hesaplar."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Cikarma islemi icin gecerli sayisal degerler girilmelidir.")
    return a - b


def multiply(a: Number, b: Number) -> Number:
    """Iki sayiyi carpar."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Carpma islemi icin gecerli sayisal degerler girilmelidir.")
    return a * b


def divide(a: Number, b: Number) -> float:
    """Iki sayiyi boler."""
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise TypeError("Bolme islemi icin gecerli sayisal degerler girilmelidir.")
    if b == 0:
        raise ValueError("Sifira bolme hatasi.")
    return float(a) / float(b)
