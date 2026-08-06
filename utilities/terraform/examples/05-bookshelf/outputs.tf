# -----------------------------------------------------------------------------
# examples/05-bookshelf -- outputs
# -----------------------------------------------------------------------------

output "bookshelf_id" {
  description = "Resource ID of the Discovery Bookshelf."
  value       = module.bookshelf.id
}
