package com.activeworkbench.mobile.share

object UrlExtractor {
    private val httpRegex = Regex(pattern = """https?://[^\\s<>()]+""", option = RegexOption.IGNORE_CASE)

    fun extractFirstHttpUrl(sharedText: String?): String? {
        if (sharedText.isNullOrBlank()) {
            return null
        }
        val match = httpRegex.find(sharedText) ?: return null
        return match.value.trimEnd('.', ',', ';', ')', ']', '}')
    }
}
