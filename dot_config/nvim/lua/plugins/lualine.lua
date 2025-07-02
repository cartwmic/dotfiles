return {
  "nvim-lualine/lualine.nvim",
  dependencies = { "nvim-tree/nvim-web-devicons", "cbochs/grapple.nvim" },
  opts = {
    sections = {
      lualine_b = { "grapple" },
    },
  },
}
