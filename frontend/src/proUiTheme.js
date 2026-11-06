const FONT_FAMILY = "PingFang SC, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const PRIMARY = "#36745c";
const PRIMARY_HOVER = "#43876d";
const PRIMARY_DARK = "#2b604b";
const PRIMARY_LIGHT = "#edf5f1";
const PRIMARY_BORDER = "#cfe1d8";
const TEXT = "#27332d";
const MUTED = "#6b756f";
const BORDER = "#e4e9e5";
const FILL = "#f7faf8";
const HOVER = "#eef5f1";

export const PROX_WORKBENCH_THEME = {
  token: {
    primary: PRIMARY,
    primaryHover: PRIMARY_HOVER,
    primaryDark: PRIMARY_DARK,
    primaryLight: PRIMARY_LIGHT,
    primaryBorder: PRIMARY_BORDER,
    text: TEXT,
    muted: MUTED,
    border: BORDER,
    page: "#ffffff",
    fill: FILL,
    hover: HOVER,
    radius: "12px",
    fontFamily: FONT_FAMILY,
  },
  // Only the layout-bearing ProX components need local density tuning. Generic
  // controls inherit the platform tokens instead of redefining every shape.
  components: {
    SidebarNav: {
      itemHeight: "30px",
      itemGap: "1px",
      itemPadding: "4px 9px",
      titleFontSize: "11px",
      titleFontWeight: "600",
      headerPadding: "4px 9px 2px",
      itemRadius: "7px",
    },
    Conversations: {
      itemHeight: "38px",
      itemGap: "1px",
      itemPadding: "3px 8px",
      itemRadius: "7px",
      groupGap: "6px",
      groupFontSize: "11px",
      groupFontWeight: "600",
    },
    Sender: {
      radius: "14px",
    },
  },
  antd: {
    token: {
      colorPrimary: PRIMARY,
      colorInfo: PRIMARY,
      colorSuccess: "#2f7d55",
      colorWarning: "#b45309",
      colorError: "#b42318",
      colorText: TEXT,
      colorTextSecondary: MUTED,
      colorTextTertiary: "#929c96",
      colorBorder: BORDER,
      colorBorderSecondary: "#eff2f0",
      colorBgContainer: "#ffffff",
      colorBgElevated: "#ffffff",
      colorBgLayout: "#f5f7f5",
      colorFillSecondary: FILL,
      colorFillTertiary: HOVER,
      colorPrimaryHover: PRIMARY_HOVER,
      colorPrimaryActive: PRIMARY_DARK,
      colorPrimaryBg: PRIMARY_LIGHT,
      colorPrimaryBorder: PRIMARY_BORDER,
      controlHeight: 36,
      controlHeightLG: 40,
      controlHeightSM: 30,
      borderRadius: 12,
      borderRadiusLG: 14,
      borderRadiusSM: 8,
      boxShadowSecondary: "0 16px 40px rgba(32, 45, 37, .12)",
      fontFamily: FONT_FAMILY,
      motionDurationMid: "0.18s",
    },
    components: {
      Form: {
        labelColor: TEXT,
        labelFontSize: 13,
        itemMarginBottom: 18,
        verticalLabelPadding: "0 0 6px",
      },
      Table: {
        headerBg: "#f7faf8",
        headerColor: MUTED,
        rowHoverBg: "#f4f8f5",
        borderColor: "#eff2f0",
        headerSplitColor: BORDER,
        cellPaddingBlock: 10,
        cellPaddingInline: 12,
        headerBorderRadius: 12,
        footerBg: "#fbfcfb",
      },
    },
  },
};
