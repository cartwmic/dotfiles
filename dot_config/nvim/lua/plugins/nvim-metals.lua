return {
  {
    "scalameta/nvim-metals",
    dependencies = {
      { "mfussenegger/nvim-dap" },
      { "nvim-lua/plenary.nvim" }, -- Also require coursier https://get-coursier.io/docs/cli-installation to install metals
    },
    event = "VeryLazy",
    config = function(_, _)
      local metals = require("metals")
      local metals_config = metals.bare_config()
      metals_config.settings = {
        showImplicitArguments = true,
      }
      metals_config.init_options.statusBarProvider = "on"
      metals_config.capabilities = require("cmp_nvim_lsp").default_capabilities()

      metals_config.on_attach = function(client, bufnr)
        metals.setup_dap()
      end

      vim.keymap.set("n", "<leader>fm", function()
        require("telescope").extensions.metals.commands()
      end, { noremap = true, desc = "Telescope Metals Commands" })

      local nvim_metals_group = vim.api.nvim_create_augroup("metals", { clear = true })
      vim.api.nvim_create_autocmd("FileType", {
        pattern = { "scala", "sbt", "java" },
        callback = function()
          metals.initialize_or_attach(metals_config)
        end,
        group = nvim_metals_group,
      })
    end,
  },
}
