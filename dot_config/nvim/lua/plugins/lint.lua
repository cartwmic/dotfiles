return {
  {
    "mfussenegger/nvim-lint",
    opts = {
      linters = {
        ["markdownlint-cli2"] = {
          args = { "--config", os.getenv("HOME") .. "/.config/.markdownlint-cli2.jsonc", "--" },
        },
      },
    },
  },
}
