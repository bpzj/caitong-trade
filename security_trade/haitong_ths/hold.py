import time
from multiprocessing import Process

import pandas as pd
import win32api
import win32con
import win32gui
from security_trade.util.win32_util import get_item_text, GuiPosition, HwndType
from security_trade.util.ocr_util import ocr_string_from_hwnd
from security_trade.util.win32_util import pos_in_window_rect


class HoldPanel:
    def __init__(self, trade_hwnd):
        self.__parent_trade = trade_hwnd
        self.__handle = None
        self.__hwnd_list = None
        # self.__edit_set = {}
        self.__data_grid_hwnd = None
        self.available_cash = None

    def __enter_hold_panel(self):
        """
        向主句柄 发送 F4，调出 查询 - 资金股票 界面
        :return:
        """
        win32gui.PostMessage(self.__parent_trade, win32con.WM_KEYDOWN, win32con.VK_F4, 0)
        win32gui.PostMessage(self.__parent_trade, win32con.WM_KEYUP, win32con.VK_F4, 0)

    def __init_handle(self):
        # 发送 F4 , 调出界面
        self.__enter_hold_panel()

        """ 获取 持仓界面的 handle 值
            每点击几次 句柄都会重建，所以先校验 保存的handle 是否有效, 如果有效, 直接使用 保存的handle
        """
        if self.__handle:
            son_of_hold = []
            win32gui.EnumChildWindows(self.__parent_trade, lambda handle, param: param.append(handle), son_of_hold)
            if self.__handle in son_of_hold:
                li = []
                win32gui.EnumChildWindows(self.__handle, lambda handle, param: param.append(handle), li)
                for l in li:
                    if win32gui.GetWindowText(l) == "资金余额":
                        return

        # 获取所有 dialog 子句柄
        def call_back(handle, hwnd_list):
            txt = win32gui.GetWindowText(handle)
            if txt and txt == "资金余额":
                hwnd_list.append(win32gui.GetParent(handle))
                return

        hwnd_l = []
        win32gui.EnumChildWindows(self.__parent_trade, call_back, hwnd_l)
        self.__handle = hwnd_l[0]

        # 调用
        self.__set_useful_handle()

    def __set_useful_handle(self):
        """
        根据 持仓界面的 handle 获取 可用资金 数值， 持仓
        :return:
        """
        # 获得 根据子句柄
        li = []
        win32gui.EnumChildWindows(self.__handle, lambda handle, param: param.append(handle), li)
        for i in range(0, len(li)):
            if win32gui.GetWindowText(li[i]) == "可用金额":
                self.available_cash = float(win32gui.GetWindowText(li[i + 3]))
            elif win32gui.GetClassName(li[i]) == "CVirtualGridCtrl":
                self.__data_grid_hwnd = li[i]

    def get_hold(self):
        # 将窗口调到前台，激活
        self.__init_handle()
        # 另起进程处理输入验证码问题
        confirm_pro = Process(target=handle_verify, args=(self.__parent_trade, self.__handle, self.__data_grid_hwnd))
        confirm_pro.start()
        # ctrl c
        win32api.keybd_event(win32con.VK_LCONTROL, 0, 0, 0)
        # 使用 PostMessage 导致客户端退出
        win32gui.SendMessage(self.__data_grid_hwnd, win32con.WM_KEYDOWN, win32api.VkKeyScan('c'), 0)
        win32gui.SendMessage(self.__data_grid_hwnd, win32con.WM_KEYUP, win32api.VkKeyScan('c'), 0)
        win32api.keybd_event(win32con.VK_LCONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)

        df = pd.read_clipboard(converters={'证券代码': str}).drop(
            columns=['冻结数量', '交易市场', '股东帐户', '汇率', '成本价港币', '成本价港币', '买入成本价港币', '买入在途数量', '卖出在途数量', 'Unnamed: 17', ])
        # 返回持仓数量大于 0 的股票
        return df[df["股票余额"] > 0]


def handle_verify(parent_trade_hwnd, hold_panel_hwnd, data_grid_hwnd):
    #
    # 1. 可以根据 验证码弹窗的 OWNER 句柄 = 父句柄 判断
    # 2. 可以根据 弹出窗口大小判断更快，所以按大小判断
    def call_back(handle, dialog_l):
        _left, _top, _right, _bottom = win32gui.GetWindowRect(handle)
        if win32gui.GetClassName(handle) == "#32770" and \
                win32gui.GetWindow(handle, win32con.GW_OWNER) == parent_trade_hwnd:
            if win_is_verify_code(handle):
                dialog_l.append(handle)

    # todo
    """ 下单 时不论成功失败，肯定在最后有一个 提示 弹框 """
    while True:
        dialog_list = []  # 对话框的长度
        win32gui.EnumWindows(call_back, dialog_list)
        # 获得 每个 dialog 句柄的子句柄，判断出是 提示 弹出窗

        # 如果提示窗口过多,表示有错误;  如果没有提示信息窗口，等待弹出窗口
        if len(dialog_list) > 1:
            exit(-1)
        if len(dialog_list) == 0:
            time.sleep(0.1)
            continue

        if len(dialog_list) == 1:
            dialog_hwnd, pic_hwnd, input_hwnd = dialog_list[0], -1, -1
            dialog_sons = []
            win32gui.EnumChildWindows(dialog_hwnd, lambda handle, param: param.append(handle), dialog_sons)
            dialog_rect = win32gui.GetWindowRect(dialog_hwnd)
            pic = GuiPosition(HwndType.Static, 186, 89, 62, 23)
            input_box = GuiPosition(HwndType.Edit, 93, 90, 86, 20)
            button = GuiPosition(HwndType.Button, 96, 149, 60, 24)
            for dialog in dialog_sons:
                if pos_in_window_rect(pic, dialog_rect, dialog):
                    pic_hwnd = dialog
                elif pos_in_window_rect(input_box, dialog_rect, dialog):
                    input_hwnd = dialog
                elif pos_in_window_rect(button, dialog_rect, dialog):
                    button_hwnd = dialog

            # todo 验证码弹框, 使用ocr识别
            identify_code = "1234"
            identify_code = ocr_string_from_hwnd(pic_hwnd, expand=10)
            win32gui.SendMessage(input_hwnd, win32con.WM_SETTEXT, None, identify_code)
            win32api.PostMessage(button_hwnd, win32con.WM_LBUTTONDOWN, None, None)
            win32api.PostMessage(button_hwnd, win32con.WM_LBUTTONUP, None, None)
            return

        # 判断窗口是不是提示窗口，是，就返回true


def win_is_verify_code(hand):
    text = ""
    sons = []
    win32gui.EnumChildWindows(hand, lambda handle, param: param.append(handle), sons)
    for son in sons:
        if win32gui.GetClassName(son) in ["Static", "Button"]:
            t = get_item_text(son)
            if t:
                text = text + t
    return '检测到您正在拷贝数据' in text and "提示" in text and '确定' in text


if __name__ == '__main__':
    hwnd = win32gui.FindWindow("#32770", "Save As")
    win32gui.ShowWindow(hwnd, win32con.SW_SHOWNORMAL)
    win32gui.SetForegroundWindow(hwnd)

    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, win32con.VK_MENU, 0x20380001)
    # win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, win32api.VkKeyScan('s'), 1 << 29)
    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYDOWN, win32api.VkKeyScan('s'), 0x20200001)
    win32gui.PostMessage(hwnd, win32con.WM_SYSCHAR, 0x76, 0x20200001)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, win32con.WM_SYSKEYUP, win32api.VkKeyScan('s'), 0xE0200001)
    win32gui.PostMessage(hwnd, win32con.WM_KEYUP, win32con.VK_MENU, 0xC0380001)

    pass
