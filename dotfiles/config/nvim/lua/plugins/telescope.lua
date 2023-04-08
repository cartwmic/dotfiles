local lazy = require("lazyvim.util.init")

return {
  {
    "nvim-telescope/telescope.nvim",
    keys = {
      {
        "<leader>fa",
        function()
          require("telescope.builtin").find_files({
            cwd = lazy.get_root(),
            no_ignore = true,
            no_ignore_parent = true,
            show_untracked = true,
            hidden = true,
          })
        end,
        desc = "Find All Files",
      },
    },
  },
}
