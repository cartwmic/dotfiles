
-- As of 2023-09-25 I couldn't get this to work because line 12 doesn't work for some reason
-- lualine comes with defaults in ~/.local/share/nvim/lazy/LazyVim/lua/lazyvim/plugins/ui.lua
return {
  {
    "nvim-lualine/lualine.nvim",
    optional = true,
    event = "VeryLazy",
    opts = function(_, opts)
      local Util = require("lazyvim.util")
      table.insert(opts.sections.lualine_x, 3, {
        function() return vim.g["metals_status"] or "metals_status not enabled in nvim-metals config" end,
        cond = function () return package.loaded["metals"] end,
        color = Util.fg("Debug"),
      })
    end,
  },
}
