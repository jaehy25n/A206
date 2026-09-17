import org.gradle.api.tasks.Exec

// Top-level build file where you can add configuration options common to all sub-projects/modules.
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.compose) apply false
    alias(libs.plugins.kotlin.serialization) apply false
    alias(libs.plugins.ksp) apply false
    alias(libs.plugins.ktlint) apply false
}

tasks.register<Exec>("installGitHooks") {
    group = "verification"
    description = "Git hook으로 저장소의 .githooks 디렉터리를 사용합니다."
    workingDir = rootDir
    commandLine("git", "config", "core.hooksPath", file(".githooks").absolutePath)
}
