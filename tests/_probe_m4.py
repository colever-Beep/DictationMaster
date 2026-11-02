import inspect
import qfluentwidgets as q
comps = ["Slider","SpinBox","DoubleSpinBox","SwitchButton","ComboBox","ToolButton",
         "TransparentToolButton","PrimaryPushButton","PushButton","InfoBar","InfoBarPosition",
         "CardWidget","StrongBodyLabel","BodyLabel","CaptionLabel","TitleLabel","FluentIcon",
         "LineEdit","Pivot","ProgressRing","IndeterminateProgressBar","TransparentPushButton",
         "HyperlinkButton","SubtitleLabel","SettingCardGroup","OptionsSettingCard","SwitchSettingCard",
         "RangeSettingCard","ComboBoxSettingCard"]
for c in comps:
    print(("OK " if hasattr(q,c) else "NO ")+c)
print("--- Slider sig ---")
try: print("Slider:", inspect.signature(q.Slider.__init__))
except Exception as e: print("err",e)
print("SwitchButton checkedChanged:", "checkedChanged" in dir(q.SwitchButton))
try: print("SpinBox:", inspect.signature(q.SpinBox.__init__))
except Exception as e: print("err",e)
try: print("DoubleSpinBox:", inspect.signature(q.DoubleSpinBox.__init__))
except Exception as e: print("err",e)
try: print("ComboBox:", inspect.signature(q.ComboBox.__init__))
except Exception as e: print("err",e)
# signal names
print("Slider has valueChanged:", "valueChanged" in dir(q.Slider))
print("SpinBox has valueChanged:", "valueChanged" in dir(q.SpinBox))
print("SwitchButton has checkedChanged:", "checkedChanged" in dir(q.SwitchButton))
