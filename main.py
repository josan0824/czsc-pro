import re
from datetime import datetime, timedelta
from pathlib import Path

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.AnimatePlotDriver import CAnimateDriver
from Plot.PlotDriver import CPlotDriver


def safe_filename_part(value):
    return re.sub(r'[\\/:*?"<>|\s]+', "_", value).strip("_") or "unknown"


def normalize_code(code):
    code = code.strip()
    match = re.fullmatch(r"(?i)(SH|SZ)(\d{6})", code)
    if match:
        return f"{match.group(2)}.{match.group(1).upper()}"
    return code.upper()


def get_stock_name(code, data_src):
    if data_src != DATA_SRC.BAO_STOCK:
        return code
    try:
        import baostock as bs

        should_logout = False
        if not getattr(bs, "lg", None) or not bs.lg.islogin:
            login_result = bs.login()
            should_logout = login_result.error_code == "0"
        rs = bs.query_stock_basic(code=code)
        if rs.error_code == "0" and rs.next():
            row = rs.get_row_data()
            if len(row) >= 2 and row[1]:
                return row[1]
    except Exception:
        pass
    finally:
        if "should_logout" in locals() and should_logout:
            bs.logout()
    return code


def generate_chart(code, begin_time, end_time, data_src, lv_list, config, plot_config, plot_para):
    normalized_code = normalize_code(code)
    chan = CChan(
        code=normalized_code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=data_src,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    if not config.trigger_step:
        plot_driver = CPlotDriver(
            chan,
            plot_config=plot_config,
            plot_para=plot_para,
        )
        output_dir = Path("Output")
        output_dir.mkdir(exist_ok=True)
        stock_name = safe_filename_part(get_stock_name(normalized_code, data_src))
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        output_path = output_dir / f"{stock_name}_{timestamp}.png"
        plot_driver.save2img(output_path)
        print(f"saved: {output_path}")
        return output_path

    CAnimateDriver(
        chan,
        plot_config=plot_config,
        plot_para=plot_para,
    )
    return None


def main():
    codes = [
        "SH000001",
#        "000001.SZ",
        #        "000905.SH",
        # "SH000852",
        #"SH000300",
        #"SH000016",
        #"688111.SH",
        #"002475.SZ",
    ]

    begin_time = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d")
    end_time = None
    data_src = DATA_SRC.MOOTDX
    lv_list = [KL_TYPE.K_1M]

    config = CChanConfig({
        "bi_strict": True,
        "bi_fx_check": "totally",
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": '1,2,3a,1p,2s,3b',
        "print_warning": True,
        "zs_algo": "normal",
    })

    plot_config = {
        "plot_kline": True,
        "plot_kline_combine": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_eigen": False,
        "plot_zs": True,
        "plot_macd": False,
        "plot_mean": False,
        "plot_channel": False,
        "plot_bsp": True,
        "plot_extrainfo": False,
        "plot_demark": False,
        "plot_marker": False,
        "plot_rsi": False,
        "plot_kdj": False,
    }

    plot_para = {
        "seg": {
            # "plot_trendline": True,
        },
        "bi": {
            # "show_num": True,
            # "disp_end": True,
        },
        "figure": {
            "x_range": 0,
        },
        "marker": {
            # "markers": {  # text, position, color
            #     '2023/06/01': ('marker here', 'up', 'red'),
            #     '2023/06/08': ('marker here', 'down')
            # },
        }
    }
    for code in codes:
        try:
            generate_chart(
                code=code,
                begin_time=begin_time,
                end_time=end_time,
                data_src=data_src,
                lv_list=lv_list,
                config=config,
                plot_config=plot_config,
                plot_para=plot_para,
            )
        except Exception as err:
            print(f"failed: {code} -> {err}")


if __name__ == "__main__":
    main()
