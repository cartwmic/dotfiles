local util = require("lspconfig.util")

return {
  {
    "neovim/nvim-lspconfig",
    opts = {
      -- you can do any additional lsp server setup here
      -- return true if you don't want this server to be setup with lspconfig
      ---@type table<string, fun(server:string, opts:_.lspconfig.options):boolean?>
      setup = {
        yamlls = function(_, _)
          require("lspconfig").yamlls.setup({
            on_attach = function(client, buffer)
              -- for some reason this is set to false even though yamlls supports it
              if client.name == "yamlls" then
                client.server_capabilities.documentFormattingProvider = true
              end
              -- need to redo the side effects of these on_attach since I've updated server_capabilities
              -- and they depend on the values of server_capabilities
              -- require("lazyvim.plugins.lsp.format").on_attach(client, buffer)
              require("lazyvim.plugins.lsp.keymaps").on_attach(client, buffer)
              on_attach(client, buffer)
            end,
            settings = {
              yaml = {
                keyOrdering = false,
                format = {
                  enable = true,
                },
              },
            },
          })
          return true
        end,
        html = function(_, _)
          --Enable (broadcasting) snippet capability for completion
          local capabilities = vim.lsp.protocol.make_client_capabilities()
          capabilities.textDocument.completion.completionItem.snippetSupport = true

          require("lspconfig").html.setup({
            capabilities = capabilities,
            filetypes = { "html", "htmldjango" },
          })
          return true
        end,
        -- example to setup with typescript.nvim
        -- tsserver = function(_, opts)
        --   require("typescript").setup({ server = opts })
        --   return true
        -- end,
        -- Specify * to use this function as a fallback for any server
        -- ["*"] = function(server, opts) end,
      },
    },
  },
}
