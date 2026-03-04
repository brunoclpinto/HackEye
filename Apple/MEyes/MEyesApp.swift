//
//  MEyesApp.swift
//  MEyes
//
//  Created by Bruno Pinto on 23/02/2026.
//

import SwiftUI
import MWDATCore

@main
struct MEyesApp: App {
    init() {
        try? Wearables.configure()
    }

    var body: some Scene {
        WindowGroup {
            MainView()
        }
    }
}
