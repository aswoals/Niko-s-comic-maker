# -*- coding: utf-8 -*-
import nk_detail as D


def test_crop_box_square_inside_image():
    x0, y0, x1, y1 = D.crop_box((10, 20, 50, 60), 400, 300)
    assert x1 - x0 == y1 - y0 >= D.MIN_CROP and x0 >= 0 and y0 >= 0 and x1 <= 400 and y1 <= 300
    x0, y0, x1, y1 = D.crop_box((380, 280, 399, 299), 400, 300)
    assert x1 <= 400 and y1 <= 300


def test_overlapping_hands_merge():
    m = D._merge([("hand", (0, 0, 10, 10), 0), ("hand", (5, 5, 20, 20), 1), ("foot", (6, 6, 9, 9), 0)])
    assert ("hand", (0, 0, 20, 20), 0) in m and len(m) == 2


def test_part_mask_covers_part():
    m = D.part_mask((100, 100, 140, 140), (60, 60, 180, 180))
    assert m.size == (D.SIDE, D.SIDE) and m.getpixel((D.SIDE // 2, D.SIDE // 2)) > 200 and m.getpixel((2, 2)) < 10
